"""Trusted scanner entry point, staged independently of candidate image content."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess  # nosec B404  # NOSONAR -- Bandit requires its suppression inline.
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

DEVICE = Path("/dev/disk/by-id/google-shifter-candidate")
ROOT = Path("/mnt/shifter-candidate")
FAILURE_MESSAGES = {
    "candidate has no supported read-only root filesystem": "root_filesystem_unavailable",
    "candidate filesystem is not safely mounted": "unsafe_mount",
    "candidate retains private build material": "build_material_residue",
    "candidate retains cloud initialization material": "cloud_initialization_residue",
    "candidate retains private metadata script material": "metadata_script_residue",
    "candidate retains a machine identity": "machine_identity_residue",
    "candidate retains a D-Bus machine identity": "dbus_identity_residue",
    "candidate D-Bus identity contains an unexpected link": "dbus_identity_link",
    "candidate retains an SSH host identity": "ssh_host_identity_residue",
    "candidate retains root SSH material": "root_ssh_residue",
    "candidate retains user SSH material": "user_ssh_residue",
    "candidate sanitization path contains a link": "sanitization_path_link",
    "candidate profile verification failed": "profile_verification_failed",
    "candidate root mount failed": "root_mount_failed",
}
FAILURE_CODES = frozenset((*FAILURE_MESSAGES.values(), "scanner_failed"))


def _raw_disk_module() -> ModuleType:
    """Load the verifier's contained helper under Python isolated mode."""
    spec = importlib.util.spec_from_file_location("trusted_raw_disk", Path(__file__).with_name("raw_disk.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_output(command: list[str], *, limit: int = 65536) -> bytes:
    """Bound retained tool output; the guest deadline bounds its execution."""
    with tempfile.TemporaryFile() as output:
        subprocess.run(  # noqa: S603  # nosec B603
            command,
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
        output.seek(0)
        data = output.read(limit + 1)
    if len(data) > limit:
        raise ValueError("scanner tool output exceeds the profile bound")
    return data


def _root_partition() -> str:
    """The initial Ubuntu profile mounts only a read-only ext4 candidate partition."""
    tree = json.loads(_run_output(["/usr/bin/lsblk", "-b", "-J", "-o", "PATH,TYPE,SIZE,FSTYPE,RO", str(DEVICE)]))
    pending = list(tree["blockdevices"])
    partitions = []
    visited = 0
    while pending:
        entry = pending.pop()
        visited += 1
        if visited > 64:
            raise ValueError("candidate partition graph exceeds the profile bound")
        pending.extend(entry.get("children", []))
        if entry.get("fstype") == "ext4" and entry.get("ro") and entry.get("path"):
            partitions.append(entry)
    if not partitions:
        raise ValueError("candidate has no supported read-only root filesystem")
    selected = max(partitions, key=lambda entry: int(entry["size"]))
    path = Path(selected["path"]).resolve(strict=True)
    if not path.is_relative_to("/dev"):
        raise ValueError("candidate partition is not a device")
    return str(path)


def inspect_output(raw_disk: ModuleType) -> dict[str, str]:
    """Execute only the independently staged verifier against a non-executable mount."""
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    partition = _root_partition()
    try:
        _run_output(["/usr/bin/mount", "-t", "ext4", "-o", "ro,noload,nosuid,nodev,noexec", partition, str(ROOT)])
    except subprocess.SubprocessError:
        raise ValueError("candidate root mount failed") from None
    try:
        options = (
            _run_output(["/usr/bin/findmnt", "-n", "-o", "OPTIONS", "--target", str(ROOT)]).decode().strip().split(",")
        )
        if not {"ro", "nosuid", "nodev", "noexec"}.issubset(options):
            raise ValueError("candidate filesystem is not safely mounted")
        raw_disk.verify_sanitized_root(ROOT)
        context = Path(__file__).parent / "context"
        try:
            values = json.loads(_run_output(["/bin/bash", str(context / "verify.sh"), str(ROOT)], limit=8192))
        except subprocess.SubprocessError:
            raise ValueError("candidate profile verification failed") from None
        if (
            not isinstance(values, dict)
            or len(values) > 32
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not 1 <= len(key) <= 256
                or not 1 <= len(value) <= 256
                for key, value in values.items()
            )
        ):
            raise ValueError("invalid profile verification result")
        return values
    finally:
        _run_output(["/usr/bin/umount", str(ROOT)])


def scan_observation(*, verify_output: bool) -> dict[str, Any]:
    """Return either complete evidence or one closed, non-sensitive failure code."""
    try:
        raw_disk = _raw_disk_module()
        observation = raw_disk.measure_device(DEVICE)
        if verify_output:
            observation.update(constraint_values=inspect_output(raw_disk), sanitized=True)
        return observation
    except Exception as exc:
        return {"failure_code": FAILURE_MESSAGES.get(str(exc), "scanner_failed")}


def main() -> None:
    """Emit one bounded nonce-bound observation from the credentialless scanner."""
    nonce = str(UUID(sys.argv[1]))
    if sys.argv[2:] not in ([], ["--verify-output"]):
        raise ValueError("invalid scanner mode")
    observation = scan_observation(verify_output=bool(sys.argv[2:]))
    encoded = base64.b64encode(json.dumps(observation, sort_keys=True).encode()).decode()
    with Path("/dev/ttyS0").open("w") as console:
        console.write(f"SHIFTER_PREPARATION_OBSERVATION:{nonce}:{encoded}\n")
    subprocess.run(  # nosec B603  # NOSONAR -- fixed executable and arguments.
        ["/sbin/poweroff"], check=True
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Console output is available to cloud operators. Never emit private
        # context, candidate file contents, or exception detail on failure.
        raise SystemExit("preparation scanner failed") from None
