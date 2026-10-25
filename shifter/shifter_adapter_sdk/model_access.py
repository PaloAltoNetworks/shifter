"""Linux guest token helper, deployable as a standalone standard-library script.

Enrollment arrives on stdin over trusted guest transport. Only opaque broker
capabilities are stored. Mount the state directory into a client container so
atomic refresh remains visible; the directory must belong to the client UID.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import ssl
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

_MAX_BYTES = 32768
_TOKEN = re.compile(r"[0-9a-f-]{36}\.[A-Za-z0-9_-]{43}")
_ORIGIN = re.compile(r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[1-9][0-9]{0,4})?")
_PAIR_KEYS = {"access_token", "refresh_token", "access_expires_at", "hard_expires_at"}


class ModelAccessError(Exception):
    """Closed error safe to expose without credential or transport details."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelAccessError("Model access unavailable")


def _object(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    if len(raw) > _MAX_BYTES:
        raise ValueError
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError
    return value


def _time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError
    return moment


def _pair(value: dict) -> dict:
    if set(value) != _PAIR_KEYS or not all(isinstance(value[key], str) for key in value):
        raise ValueError
    if not all(_TOKEN.fullmatch(value[key]) for key in ("access_token", "refresh_token")):
        raise ValueError
    if not datetime.now(UTC) < _time(value["access_expires_at"]) <= _time(value["hard_expires_at"]):
        raise ValueError
    return value


def _post(config: dict, route: str, payload: dict) -> dict:
    origin, ca = config["broker_url"], config["ca_pem"]
    if not isinstance(origin, str) or not _ORIGIN.fullmatch(origin) or not isinstance(ca, str):
        raise ValueError
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=ca)
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect())
    request = Request(
        origin + "/v1/access/" + route,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError
        return _object(response.read(_MAX_BYTES + 1))


def _secure(fd: int, *, directory: bool = False) -> None:
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise ValueError
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError
    if not directory and info.st_nlink != 1:
        raise ValueError


@contextmanager
def _locked(path: Path):
    if not path.is_absolute() or path.name != "session.json":
        raise ValueError
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _secure(directory, directory=True)
        lock = os.open("session.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            _secure(lock)
            deadline = time.monotonic() + 15
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError from None
                    time.sleep(0.05)
            yield directory
        finally:
            os.close(lock)
    finally:
        os.close(directory)


def _read(directory: int) -> dict:
    fd = os.open("session.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        _secure(stream.fileno())
        return _object(stream.read(_MAX_BYTES + 1))


def _write(directory: int, value: dict) -> None:
    raw = json.dumps(value, separators=(",", ":")).encode()
    if len(raw) > _MAX_BYTES:
        raise ValueError
    # Relative to the pinned directory even if an ancestor is renamed.
    fd, name = tempfile.mkstemp(prefix=".session-", dir=f"/proc/self/fd/{directory}")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, "session.json", dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def enroll(path: Path, payload: bytes) -> None:
    """Consume one-use enrollment without writing its raw token to disk."""
    try:
        value = _object(payload)
        if set(value) != {"broker_url", "ca_pem", "enrollment_token"}:
            raise ValueError
        token = value.pop("enrollment_token")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ValueError
        with _locked(path) as directory:
            pair = _pair(_post(value, "exchange", {"token": token}))
            _write(directory, {**value, **pair})
    except Exception:
        raise ModelAccessError("Model enrollment unavailable") from None


def access_token(path: Path) -> str:
    """Serialize refresh across client processes and return a short-lived token."""
    try:
        with _locked(path) as directory:
            value = _read(directory)
            if set(value) != {"broker_url", "ca_pem"} | _PAIR_KEYS:
                raise ValueError
            now = datetime.now(UTC)
            if _time(value["hard_expires_at"]) <= now:
                raise ValueError
            if not isinstance(value["refresh_token"], str) or not _TOKEN.fullmatch(value["refresh_token"]):
                raise ValueError
            if (_time(value["access_expires_at"]) - now).total_seconds() < 30:
                pair = _pair(_post(value, "refresh", {"token": value["refresh_token"]}))
                if _time(pair["hard_expires_at"]) > _time(value["hard_expires_at"]):
                    raise ValueError
                value.update(pair)
                _write(directory, value)
            token = value["access_token"]
            if not isinstance(token, str) or not _TOKEN.fullmatch(token):
                raise ValueError
            return token
    except Exception:
        raise ModelAccessError("Model access unavailable") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Shifter guest model access")
    parser.add_argument("operation", choices=("enroll", "token"))
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "enroll":
            enroll(args.state, sys.stdin.buffer.read(_MAX_BYTES + 1))
        else:
            print(access_token(args.state))
    except ModelAccessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
