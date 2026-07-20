"""Stage an object-storage-backed ACES package into a local pack root (#1567).

Object-backed ``AcesPackageSource`` rows carry a ``package_ref`` that names one
immutable archive object in object storage (ADR-034-R5). Registration defers
their content validation and digest binding, so this launch-time resolver is
where object refs earn the *equivalent identity guarantees* repo packs get: it
downloads that single bounded, immutable archive into a private temporary
directory, safely extracts it under hard size / entry-count / no-traversal /
no-symlink / no-special-file guards, and yields the contained pack root for the
caller to validate (``validate_pack``) and digest-verify (``verify_pack_digest``)
before any SDL resolution, parsing, planning, or dispatch.

The ``ObjectStorage`` is dependency-injected by the caller, so this module never
imports ``cms`` / ``engine`` and does no provider selection itself. It reuses the
existing ``AcesPackageError`` rather than introducing a parallel exception
hierarchy (ADR-031-R1 / ADR-024).
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from shared.aces.package_loader import AcesPackageError
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from collections.abc import Iterator

    from shared.cloud.types import ObjectStorage

logger = logging.getLogger(__name__)

_ARCHIVE_NAME = "package-archive"
_EXTRACT_DIRNAME = "pack"


@contextmanager
def stage_object_pack(
    *,
    storage: ObjectStorage,
    bucket: str,
    key: str,
    max_archive_bytes: int,
    max_uncompressed_bytes: int,
    max_entries: int,
) -> Iterator[Path]:
    """Download and safely extract one object-backed pack; yield its pack root.

    Heads the object to size-gate before transfer, downloads the single archive
    bound to that exact version (a replacement mid-flight fails closed), extracts
    it under the guards below, and yields the single contained pack-root
    directory. The private staging directory is always removed on exit, whether
    the body succeeds or raises. Digest and contract validation are the caller's
    responsibility against the yielded root (ADR-034-R5).

    Args:
        storage: Injected object-storage adapter (provider selection is the
            caller's; this module is provider-neutral).
        bucket: Object-storage bucket holding the package archive.
        key: Object key of the single immutable package archive.
        max_archive_bytes: Hard cap on the downloaded archive size.
        max_uncompressed_bytes: Hard cap on total declared uncompressed bytes.
        max_entries: Hard cap on archive member count.

    Yields:
        The extracted pack-root directory (a single top-level directory).

    Raises:
        AcesPackageError: on missing config, over-size, retrieval failure, an
            unsafe archive, or a malformed pack shape.
    """
    from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError

    if not bucket or not bucket.strip() or not key or not key.strip():
        raise AcesPackageError("object package storage location is not configured")

    staging = Path(tempfile.mkdtemp(prefix="aces-object-pack-"))
    try:
        try:
            identity = storage.head_object(bucket, key)
        except CloudStorageError as exc:
            raise AcesPackageError(f"object package could not be located: {safe_log_value(exc)}") from exc
        declared_size = int(identity.get("content_length", 0) or 0)
        if declared_size > max_archive_bytes:
            raise AcesPackageError("object package archive exceeds the configured size bound")

        archive_path = staging / _ARCHIVE_NAME
        try:
            storage.download_object(
                bucket,
                key,
                str(archive_path),
                max_bytes=max_archive_bytes,
                expected_identity=identity,
            )
        except ObjectPreconditionError as exc:
            raise AcesPackageError("object package changed during retrieval") from exc
        except CloudStorageError as exc:
            raise AcesPackageError(f"object package could not be retrieved: {safe_log_value(exc)}") from exc

        extract_dir = staging / _EXTRACT_DIRNAME
        extract_dir.mkdir()
        _safe_extract(
            archive_path,
            extract_dir,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_entries=max_entries,
        )
        yield _single_pack_root(extract_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _safe_extract(
    archive_path: Path,
    dest: Path,
    *,
    max_uncompressed_bytes: int,
    max_entries: int,
) -> None:
    """Extract ``archive_path`` under ``dest`` with fail-closed content guards.

    Pre-scans every member to reject links, special/device files, absolute and
    traversal paths, an over-count of entries, and an over-budget total declared
    size, then extracts with the stdlib ``data`` filter (PEP 706) as a second,
    independent containment layer.
    """
    try:
        with tarfile.open(archive_path, mode="r:*") as tar:
            _scan_members(tar.getmembers(), max_uncompressed_bytes=max_uncompressed_bytes, max_entries=max_entries)
            tar.extractall(path=dest, filter="data")
    except AcesPackageError:
        raise
    except tarfile.TarError as exc:
        raise AcesPackageError(f"object package archive could not be extracted: {safe_log_value(exc)}") from exc


def _scan_members(
    members: list[tarfile.TarInfo],
    *,
    max_uncompressed_bytes: int,
    max_entries: int,
) -> None:
    """Pre-scan members: reject unsafe entries and enforce count/size bounds."""
    if len(members) > max_entries:
        raise AcesPackageError("object package archive has too many entries")
    total = 0
    for member in members:
        _reject_unsafe_member(member)
        if member.isreg():
            total += member.size
            if total > max_uncompressed_bytes:
                raise AcesPackageError("object package archive exceeds the uncompressed size bound")


def _reject_unsafe_member(member: tarfile.TarInfo) -> None:
    """Reject any archive member that is not a plain contained file or directory."""
    _reject_unsafe_member_type(member)
    _reject_unsafe_member_path(member.name)


def _reject_unsafe_member_type(member: tarfile.TarInfo) -> None:
    """Reject link, special-device, and other non-file/non-directory members."""
    if member.issym() or member.islnk():
        raise AcesPackageError("object package archive contains a link entry")
    if member.ischr() or member.isblk() or member.isfifo():
        raise AcesPackageError("object package archive contains a special-device entry")
    if not (member.isreg() or member.isdir()):
        raise AcesPackageError("object package archive contains an unsupported entry type")


def _reject_unsafe_member_path(name: str) -> None:
    """Reject absolute paths and parent-directory traversal in a member name."""
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        raise AcesPackageError("object package archive contains an absolute path")
    if ".." in PurePosixPath(name).parts:
        raise AcesPackageError("object package archive contains a path-traversal entry")


def _single_pack_root(extract_dir: Path) -> Path:
    """Return the single top-level directory in ``extract_dir`` (the pack root)."""
    entries = list(extract_dir.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise AcesPackageError("object package archive must contain exactly one top-level pack directory")
    return entries[0].resolve()
