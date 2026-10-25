"""Fetch, integrity-verify, and extract one file from a public npm package.

Everything streams to disk: memory use does not depend on the package size. The
registry host is pinned, the tarball URL the registry returns must stay on that
host, and the npm ``dist.integrity`` (sha512) must match before any byte is used.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

REGISTRY_HOST = "registry.npmjs.org"
_REGISTRY = f"https://{REGISTRY_HOST}"
_CHUNK = 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)


class NpmAcquisitionError(RuntimeError):
    """A value-free npm acquisition failure safe to record on the artifact row."""


@dataclass(frozen=True)
class FetchedFile:
    """One extracted file on local disk with its identity."""

    path: Path
    sha256: str
    byte_count: int
    upstream_ref: str
    upstream_integrity: str


def _manifest(client: httpx.Client, package: str, version: str) -> tuple[str, str]:
    """Return ``(tarball_url, sha512_integrity)`` for one exact package version."""
    response = client.get(f"{_REGISTRY}/{quote(package, safe='@')}/{quote(version, safe='')}")
    if response.status_code == httpx.codes.NOT_FOUND:
        raise NpmAcquisitionError("npm package version not found")
    if response.status_code != httpx.codes.OK:
        raise NpmAcquisitionError(f"npm registry returned HTTP {response.status_code}")
    dist = response.json().get("dist") or {}
    tarball, integrity = dist.get("tarball"), dist.get("integrity")
    if not isinstance(tarball, str) or not isinstance(integrity, str) or not integrity.startswith("sha512-"):
        raise NpmAcquisitionError("npm registry manifest lacks a sha512 tarball integrity")
    parsed = urlparse(tarball)
    if parsed.scheme != "https" or parsed.hostname != REGISTRY_HOST:
        raise NpmAcquisitionError("npm tarball is not served from the pinned registry")
    return tarball, integrity


def _download(client: httpx.Client, url: str, integrity: str, destination: Path) -> None:
    """Stream the tarball to ``destination`` and verify its sha512 integrity."""
    digest = hashlib.sha512()
    with client.stream("GET", url) as response:
        if response.status_code != httpx.codes.OK:
            raise NpmAcquisitionError(f"npm tarball download returned HTTP {response.status_code}")
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes(_CHUNK):
                digest.update(chunk)
                handle.write(chunk)
    expected = integrity.removeprefix("sha512-")
    if base64.b64encode(digest.digest()).decode("ascii") != expected:
        raise NpmAcquisitionError("npm tarball integrity mismatch")


def _extract(tarball: Path, member: str, destination: Path) -> tuple[str, int]:
    """Copy exactly one regular-file member out of the tarball; return its identity."""
    with tarfile.open(tarball, "r:gz") as archive:
        try:
            info = archive.getmember(member)
        except KeyError:
            raise NpmAcquisitionError("npm package does not contain the recipe member") from None
        if not info.isreg():
            raise NpmAcquisitionError("npm package recipe member is not a regular file")
        source = archive.extractfile(info)
        if source is None:
            raise NpmAcquisitionError("npm package recipe member is unreadable")
        digest = hashlib.sha256()
        size = 0
        with source, destination.open("wb") as handle:
            while chunk := source.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                handle.write(chunk)
    if size != info.size:
        raise NpmAcquisitionError("npm package recipe member is truncated")
    return digest.hexdigest(), size


def fetch_file(
    package: str, version: str, member: str, workdir: Path, *, client: httpx.Client | None = None
) -> FetchedFile:
    """Acquire ``member`` from ``package@version`` into ``workdir``."""
    owned = client is None
    http = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=False)
    try:
        tarball_url, integrity = _manifest(http, package, version)
        tarball = workdir / "package.tgz"
        _download(http, tarball_url, integrity, tarball)
    except httpx.HTTPError as exc:
        raise NpmAcquisitionError(f"npm request failed ({type(exc).__name__})") from None
    finally:
        if owned:
            http.close()
    extracted = workdir / "artifact"
    sha256, size = _extract(tarball, member, extracted)
    tarball.unlink()
    return FetchedFile(
        path=extracted,
        sha256=sha256,
        byte_count=size,
        upstream_ref=f"npm:{package}@{version}",
        upstream_integrity=integrity,
    )


def clear_workdir(workdir: Path) -> None:
    """Remove every file an acquisition attempt wrote."""
    shutil.rmtree(workdir, ignore_errors=True)
