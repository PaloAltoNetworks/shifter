"""Independent raw-disk identity and the contained Linux profile's sanitization.

Run only on the approved credentialless scanner, with the candidate attached
read-only. The image's name, labels, guest agent, and builder report cannot
substitute for reading the complete block device.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import struct
from pathlib import Path
from typing import BinaryIO

MAX_DISK_BYTES = 200 * 1024**3
# Linux uapi linux/fs.h: _IO(0x12,94), _IOR(0x12,114,size_t), on the
# explicitly supported 64-bit Linux scanner architecture.
_BLKROGET = 0x125E
_BLKGETSIZE64 = 0x80081272


def measure_stream(stream: BinaryIO, size_bytes: int) -> dict[str, str | int]:
    """Hash exactly the complete declared device length, including sparse zeros."""
    if type(size_bytes) is not int or not 0 < size_bytes <= MAX_DISK_BYTES:
        raise ValueError("raw disk measurement exceeds the profile bound")
    digest = hashlib.sha256()
    remaining = size_bytes
    while remaining:
        block = stream.read(min(remaining, 4 * 1024**2))
        if not block:
            raise ValueError("raw disk measurement is incomplete")
        digest.update(block)
        remaining -= len(block)
    if stream.read(1):
        raise ValueError("raw disk measurement does not cover the complete device")
    return {"raw_disk_digest": "sha256:" + digest.hexdigest(), "size_bytes": size_bytes}


def measure_device(device: Path) -> dict[str, str | int]:
    """Require a kernel-enforced read-only block device before measuring bytes."""
    target = device.resolve(strict=True)
    if not target.is_relative_to("/dev") or not stat.S_ISBLK(target.stat().st_mode):
        raise ValueError("candidate is not an attached block device")
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISBLK(os.fstat(stream.fileno()).st_mode):
            raise ValueError("candidate device identity changed")
        readonly = struct.unpack("I", fcntl.ioctl(stream.fileno(), _BLKROGET, bytes(4)))[0]
        if readonly != 1:
            raise ValueError("candidate disk is not attached read-only")
        size = struct.unpack("Q", fcntl.ioctl(stream.fileno(), _BLKGETSIZE64, bytes(8)))[0]
        return measure_stream(stream, size)


def candidate_path(root: Path, relative: str) -> Path:
    """Never traverse candidate-controlled links when checking private residue."""
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("candidate sanitization path contains a link")
    return current


def _entries(directory: Path) -> list[Path]:
    """Bound inspection of the small identity directories used by this profile."""
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("candidate identity directory is invalid")
    result = []
    for index, path in enumerate(directory.iterdir()):
        if index >= 64:
            raise ValueError("candidate identity directory exceeds the profile bound")
        result.append(path)
    return result


def verify_sanitized_root(root: Path) -> None:
    """Require fresh host identity and removal of this profile's build material.

    This profile installs no accounts or credentials. Its output must contain no
    baked SSH identities, root/home SSH material, cached cloud startup input, or
    private preparation staging. Other profiles need their own qualified rules.
    """
    if candidate_path(root, "var/lib/shifter-preparation").exists():
        raise ValueError("candidate retains private build material")
    if candidate_path(root, "var/lib/cloud/instances").exists():
        raise ValueError("candidate retains cloud initialization material")
    if any(path.name.startswith("metadata-script") for path in _entries(candidate_path(root, "tmp"))):
        raise ValueError("candidate retains private metadata script material")
    _verify_machine_identities(root)
    _verify_ssh_identities(root)


def _verify_machine_identities(root: Path) -> None:
    """Handle verify machine identities."""
    machine_id = candidate_path(root, "etc/machine-id")
    if machine_id.exists() and (not machine_id.is_file() or machine_id.stat().st_size):
        raise ValueError("candidate retains a machine identity")
    dbus_id = candidate_path(root, "var/lib/dbus") / "machine-id"
    if dbus_id.is_symlink():
        if str(dbus_id.readlink()) not in {"/etc/machine-id", "../../../etc/machine-id"}:
            raise ValueError("candidate D-Bus identity contains an unexpected link")
    elif dbus_id.exists() and (not dbus_id.is_file() or dbus_id.stat().st_size):
        raise ValueError("candidate retains a D-Bus machine identity")


def _verify_ssh_identities(root: Path) -> None:
    """Handle verify ssh identities."""
    keys = _entries(candidate_path(root, "etc/ssh"))
    if any(key.name.startswith("ssh_host_") for key in keys):
        raise ValueError("candidate retains an SSH host identity")
    if _entries(candidate_path(root, "root/.ssh")):
        raise ValueError("candidate retains root SSH material")
    for home in _entries(candidate_path(root, "home")):
        if _entries(candidate_path(root, f"home/{home.name}/.ssh")):
            raise ValueError("candidate retains user SSH material")
