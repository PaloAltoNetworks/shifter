#!/usr/bin/env python3
"""Converge and verify the Polaris A14-to-A9 splice credential contract."""

from __future__ import annotations

import argparse
import base64
import os
import pwd
import re
import secrets
import stat

# Subprocess use is confined to fixed absolute executables and closed argv.
import subprocess  # nosec B404  # NOSONAR
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

KALI_HOME = Path("/home/kali")
try:
    _KALI_ACCOUNT = pwd.getpwnam("kali")
except KeyError:
    _KALI_ACCOUNT = None
KALI_UID = _KALI_ACCOUNT.pw_uid if _KALI_ACCOUNT else os.getuid()
KALI_GID = _KALI_ACCOUNT.pw_gid if _KALI_ACCOUNT else os.getgid()
CONTAINER_HELPER = "/usr/local/libexec/polaris-splice-credential.py"
HOST_HELPER = "/opt/polaris/libexec/polaris-splice-credential.py"
# Path the authoritative polaris a14-kali image installs its entrypoint at
# (scenarios repo: `COPY a14/entrypoint.sh /usr/local/bin/entrypoint.sh`). The
# compose override replaces the image entrypoint with this helper, so after
# repair() we must hand off to the a14 image's real entrypoint here; an execv of
# a nonexistent path kills PID 1 and crash-loops the container.
ORIGINAL_ENTRYPOINT = "/usr/local/bin/entrypoint.sh"
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HELPER_STAGING_FAILED = "helper staging failed"
_MANAGED_STANZA = """Host splice-relay
  HostName a9-splice
  User root
  IdentityFile /home/kali/.ssh/splice_relay
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
"""


class CredentialContractError(RuntimeError):
    """A bounded, secret-safe splice credential contract failure."""


def _paths() -> tuple[Path, Path, Path]:
    """Return the canonical Kali SSH projection paths."""
    ssh_dir = KALI_HOME / ".ssh"
    return ssh_dir, ssh_dir / "splice_relay", ssh_dir / "config"


def _require_regular_or_absent(path: Path) -> None:
    """Reject existing targets that are not regular files."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise CredentialContractError(f"{path.name} target must be a regular file")


def _prepare_ssh_directory() -> Path:
    """Create and normalize the Kali SSH directory."""
    ssh_dir, _, _ = _paths()
    try:
        mode = ssh_dir.lstat().st_mode
    except FileNotFoundError:
        ssh_dir.mkdir(parents=True, mode=0o700)
    else:
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise CredentialContractError(".ssh target must be a regular directory")
    os.chown(ssh_dir, KALI_UID, KALI_GID)
    os.chmod(ssh_dir, 0o700)
    return ssh_dir


def _decoded_private_key() -> bytes:
    """Decode the retained Compose credential without exposing it."""
    encoded = os.environ.get("KALI_SPLICE_PRIVATE_KEY_B64", "")
    if not encoded:
        raise CredentialContractError("credential environment is absent")
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
    except ValueError:
        raise CredentialContractError("invalid credential environment") from None
    if not decoded:
        raise CredentialContractError("credential environment is empty")
    return decoded


def _validate_private_key(path: Path) -> tuple[str, str]:
    """Validate a private key and return its public identity."""
    result = subprocess.run(  # noqa: S603  # nosec B603 -- fixed executable and validated local path
        ["/usr/bin/ssh-keygen", "-y", "-f", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    fields = result.stdout.strip().split()
    if result.returncode != 0 or len(fields) < 2:
        raise CredentialContractError("credential is not a usable private key")
    return fields[0], fields[1]


def _atomic_write(path: Path, content: bytes, *, validate_key: bool = False) -> None:
    """Atomically replace one owned mode-0600 projection file."""
    _require_regular_or_absent(path)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, KALI_UID, KALI_GID)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if validate_key:
            _validate_private_key(tmp)
        os.replace(tmp, path)
        os.chown(path, KALI_UID, KALI_GID)
        os.chmod(path, 0o600)
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()


def _directive(line: str) -> tuple[str, list[str]]:
    """Parse an SSH config line into its lowercase keyword and arguments."""
    fields = line.strip().split()
    return (fields[0].lower(), fields[1:]) if fields else ("", [])


def _host_line_without_splice(line: str, patterns: list[str]) -> str | None:
    """Remove the managed alias from a Host line, retaining other patterns."""
    retained = [item for item in patterns if item != "splice-relay"]
    if len(retained) == len(patterns):
        return line
    if not retained:
        return None
    indent = line[: len(line) - len(line.lstrip())]
    newline = "\n" if line.endswith("\n") else ""
    return f"{indent}Host {' '.join(retained)}{newline}"


def _without_splice_stanzas(text: str) -> str:
    """Remove existing splice-relay blocks without altering other blocks."""
    output: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        keyword, arguments = _directive(line)
        if keyword in {"host", "match"}:
            skipping = False
        if keyword == "host":
            retained_line = _host_line_without_splice(line, arguments)
            if retained_line is None:
                skipping = True
                continue
            line = retained_line
        if not skipping:
            output.append(line)
    return "".join(output).lstrip("\n")


def _converged_config(existing: str) -> str:
    """Build an idempotent config while preserving global directives."""
    retained = _without_splice_stanzas(existing)
    lines = retained.splitlines(keepends=True)
    first_block = next(
        (
            index
            for index, line in enumerate(lines)
            if (line.strip().split()[:1] or [""])[0].lower() in {"host", "match"}
        ),
        len(lines),
    )
    preamble = "".join(lines[:first_block]).rstrip()
    remainder = "".join(lines[first_block:]).strip()
    sections = [section for section in (preamble, _MANAGED_STANZA.rstrip(), remainder) if section]
    return "\n\n".join(sections) + "\n"


def repair() -> None:
    """Hydrate and validate the complete writable credential projection."""
    _, key_path, config_path = _paths()
    _prepare_ssh_directory()
    decoded = _decoded_private_key()
    _require_regular_or_absent(config_path)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    _atomic_write(key_path, decoded, validate_key=True)
    _atomic_write(config_path, _converged_config(existing).encode("utf-8"))
    check()


def _require_file_contract(path: Path, mode: int) -> None:
    """Require a nonempty regular file with exact ownership and mode."""
    _require_regular_or_absent(path)
    try:
        metadata = path.stat()
    except FileNotFoundError:
        raise CredentialContractError(f"{path.name} is missing") from None
    if metadata.st_size == 0:
        raise CredentialContractError(f"{path.name} is empty")
    if metadata.st_uid != KALI_UID or metadata.st_gid != KALI_GID:
        raise CredentialContractError(f"{path.name} ownership is invalid")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise CredentialContractError(f"{path.name} mode is invalid")


def check() -> None:
    """Validate the complete in-container credential projection."""
    ssh_dir, key_path, config_path = _paths()
    try:
        directory = ssh_dir.lstat()
    except FileNotFoundError:
        raise CredentialContractError(".ssh directory is missing") from None
    if not stat.S_ISDIR(directory.st_mode) or stat.S_ISLNK(directory.st_mode):
        raise CredentialContractError(".ssh target must be a regular directory")
    if directory.st_uid != KALI_UID or directory.st_gid != KALI_GID:
        raise CredentialContractError(".ssh ownership is invalid")
    if stat.S_IMODE(directory.st_mode) != 0o700:
        raise CredentialContractError(".ssh mode is invalid")
    _require_file_contract(key_path, 0o600)
    _validate_private_key(key_path)
    _require_file_contract(config_path, 0o600)
    try:
        config = config_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise CredentialContractError("SSH config is invalid") from None
    if config != _converged_config(config):
        raise CredentialContractError("SSH config is not converged")


def _container_name(value: str) -> str:
    """Validate a container name before placing it in Docker argv."""
    if not _CONTAINER_RE.fullmatch(value):
        raise CredentialContractError("container identity is invalid")
    return value


def _docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run Docker with bounded captured output and no shell."""
    return subprocess.run(  # noqa: S603  # nosec B603 -- closed argv assembled by this module
        ["/usr/bin/docker", *args], check=False, capture_output=True, text=True
    )


def _require_docker(args: list[str], message: str) -> subprocess.CompletedProcess[str]:
    """Run Docker and translate failure into a secret-safe error."""
    result = _docker(args)
    if result.returncode != 0:
        raise CredentialContractError(message)
    return result


def _ensure_container_helper(container: str) -> None:
    """Install this helper into a legacy container from a root-only directory."""
    if _docker(["exec", container, "test", "-x", CONTAINER_HELPER]).returncode == 0:
        return
    helper_dir = str(Path(CONTAINER_HELPER).parent)
    staged = f"{helper_dir}/.polaris-splice-credential-{secrets.token_hex(8)}.py"
    _require_docker(["exec", container, "mkdir", "-p", helper_dir], _HELPER_STAGING_FAILED)
    _require_docker(
        ["cp", str(Path(__file__).resolve()), f"{container}:{staged}"],
        _HELPER_STAGING_FAILED,
    )
    _require_docker(
        ["exec", container, "install", "-o", "root", "-g", "root", "-m", "0755", staged, CONTAINER_HELPER],
        _HELPER_STAGING_FAILED,
    )
    _docker(["exec", container, "rm", "-f", staged])


def _public_identity(output: str) -> tuple[str, str]:
    """Extract an SSH public-key algorithm and blob from command output."""
    for line in output.splitlines():
        fields = line.split()
        for index, field in enumerate(fields[:-1]):
            if field.startswith(("ssh-", "ecdsa-")):
                return field, fields[index + 1]
    raise CredentialContractError("public-key identity is unavailable")


def _host_check(container: str) -> None:
    """Validate the container projection, key pair, and gated SSH path."""
    if _docker(["exec", container, "test", "-x", CONTAINER_HELPER]).returncode != 0:
        raise CredentialContractError("container credential helper is missing")
    _require_docker(["exec", container, CONTAINER_HELPER, "check"], "container credential check failed")
    private_public = _require_docker(
        ["exec", container, "ssh-keygen", "-y", "-f", "/home/kali/.ssh/splice_relay"],
        "private-key derivation failed",
    )
    authorized = _require_docker(
        ["exec", "a9-splice", "cat", "/root/.ssh/authorized_keys"],
        "A9 authorized key check failed",
    )
    if _public_identity(private_public.stdout) != _public_identity(authorized.stdout):
        raise CredentialContractError("A14/A9 key pair mismatch")
    networks = _require_docker(
        ["inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
        "container topology check failed",
    )
    if "splice-link" in networks.stdout:
        _require_docker(
            [
                "exec",
                "--user",
                "kali",
                container,
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "root@splice-relay",
                "true",
            ],
            "post-gate splice SSH check failed",
        )


def host_check(container: str) -> None:
    """Run a read-only host-side credential health check."""
    _host_check(_container_name(container))


def host_repair(container: str) -> None:
    """Repair one container in place, then validate the full contract."""
    resolved = _container_name(container)
    _ensure_container_helper(resolved)
    _require_docker(["exec", resolved, CONTAINER_HELPER, "repair"], "container credential repair failed")
    _host_check(resolved)


def entrypoint() -> None:
    """Repair the writable projection before handing off to the image entrypoint."""
    repair()
    os.execv(ORIGINAL_ENTRYPOINT, [ORIGINAL_ENTRYPOINT])  # noqa: S606  # nosec B606 -- fixed reviewed entrypoint


def _parser() -> argparse.ArgumentParser:
    """Build the bounded command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "repair", "entrypoint", "host-check", "host-repair"))
    parser.add_argument("--container", default="a14-kali")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one helper mode and emit only a bounded status."""
    args = _parser().parse_args(argv)
    try:
        if args.mode == "check":
            check()
            outcome = "healthy"
        elif args.mode == "repair":
            repair()
            outcome = "repaired"
        elif args.mode == "host-check":
            host_check(args.container)
            outcome = "healthy"
        elif args.mode == "host-repair":
            host_repair(args.container)
            outcome = "repaired"
        else:
            entrypoint()
            return 0
    except CredentialContractError as exc:
        sys.stderr.write(f"splice-credential: failed: {exc}\n")
        return 1
    sys.stdout.write(f"splice-credential: {outcome}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
