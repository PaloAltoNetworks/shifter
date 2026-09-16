"""Verify complete build material contained in an installed adapter image.

The profile digest describes this algorithm. A specification digest binds a
canonical list of relative paths and SHA-256 file digests, ordered by path.
Permissions are deliberately not inherited: callers stage files privately with
fixed modes and invoke the entrypoints explicitly. Returned bytes are the bytes
that were hashed, so execution never reopens unverified mutable source files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_FILES = 256
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ContextError(ValueError):
    """Installed build material is missing, unsafe or does not match its identity."""


def load_context(root: Path, specification_id: str, expected_digest: str) -> dict[str, bytes]:
    """Read one closed installed context, failing before any executable effect.

    The image filesystem is read-only by workload admission. No links, special
    files, unbounded payloads or relative specification paths are accepted.
    Both builder and independently installed verifier use this same check.
    """
    if not isinstance(specification_id, str) or not _IDENTIFIER.fullmatch(specification_id):
        raise ContextError("invalid installed specification identifier")
    directory = root / specification_id
    if directory.is_symlink() or not directory.is_dir():
        raise ContextError("installed specification is unavailable")
    files = _read_tree(directory)
    if not {"build.sh", "verify.sh", "verify_boot.py"}.issubset(files):
        raise ContextError("installed context lacks build or verification material")
    if context_digest(files) != expected_digest:
        raise ContextError("installed material does not match the specification digest")
    return files


def context_digest(files: dict[str, bytes]) -> str:
    """Compute the profile's portable identity over paths and exact content."""
    rows = [{"path": path, "sha256": hashlib.sha256(files[path]).hexdigest()} for path in sorted(files)]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _read_tree(directory: Path) -> dict[str, bytes]:
    """Bound traversal and reads, rejecting filesystem indirection before use."""
    files: dict[str, bytes] = {}
    total = 0
    entries = 0
    for current, directories, names in os.walk(directory, followlinks=False):
        entries += len(directories) + len(names)
        if entries > MAX_CONTEXT_FILES:
            raise ContextError("installed context exceeds the entry limit")
        for name in directories:
            if (Path(current) / name).is_symlink():
                raise ContextError("installed context contains a link")
        for name in names:
            path, data = _read_context_file(Path(current) / name, MAX_CONTEXT_BYTES - total)
            total += len(data)
            if total > MAX_CONTEXT_BYTES:
                raise ContextError("installed context exceeds the byte limit")
            files[path.relative_to(directory).as_posix()] = data
    return files


def _read_context_file(path: Path, remaining: int) -> tuple[Path, bytes]:
    """Handle read context file."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ContextError("installed context contains a non-regular file")
    if info.st_size > remaining:
        raise ContextError("installed context exceeds the byte limit")
    # O_NOFOLLOW defends the final component; image admission protects ancestors.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return path, stream.read(remaining + 1)
