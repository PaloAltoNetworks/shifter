"""Deterministic, streamed delivery payloads for source-backed RAES content (ADR-032-R3, R9).

A ``file`` payload is the source file's bytes verbatim; a ``directory`` payload
is a reproducible (sorted, identity-normalized, uncompressed) tar of the subtree.
Payloads are produced as bounded chunks and promoted to content-addressed
object storage through a hashing reader, so memory stays constant for any size
and there is no size cap.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from shared.raes.content_delivery import ContentDeliveryError

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

    from shared.cloud.types import ObjectStorage

__all__ = ["PayloadSource", "measure", "payload_chunks", "promote"]

_FILE_FORMATS = frozenset({"", "raw", "file"})
_DIRECTORY_FORMATS = frozenset({"", "tree", "directory"})
_FILE_MODE = 0o644
#: Read size for streaming payload sources.
_CHUNK_BYTES = 1024 * 1024
_OCTET_STREAM = "application/octet-stream"


def payload_chunks(*, content_type: str, content_format: str, source_path: Path) -> Iterator[bytes]:
    """Yield the deterministic delivery payload for one content item in bounded chunks.

    ``file`` yields the file bytes verbatim; ``directory`` yields a reproducible
    (sorted, identity-normalized, uncompressed) tar of the subtree, byte-identical
    to what :mod:`tarfile` writes for the same members. Memory stays constant for
    any payload size and there is no size cap (ADR-032-R9): every member is read
    for exactly its recorded size, so a source that changes underneath fails
    closed. Any other content type or format is non-realizable and fails closed
    before anything is yielded.
    """
    if content_type == "file":
        return _file_chunks(content_format, source_path)
    if content_type == "directory":
        return _directory_chunks(content_format, source_path)
    raise ContentDeliveryError(f"content type {content_type!r} has no deterministic materializer")


def _read_exact(path: Path, size: int) -> Iterator[bytes]:
    """Yield exactly ``size`` bytes of ``path``, failing closed if it is shorter or longer."""
    remaining = size
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                raise ContentDeliveryError("content delivery source changed while it was read")
            remaining -= len(chunk)
            yield chunk
        if handle.read(1):
            raise ContentDeliveryError("content delivery source changed while it was read")


def _file_chunks(content_format: str, source_path: Path) -> Iterator[bytes]:
    """Validate a source-backed file, then return its bytes as a chunk iterator."""
    if content_format not in _FILE_FORMATS:
        raise ContentDeliveryError(f"file format {content_format!r} has no deterministic materializer")
    if source_path.is_symlink() or not source_path.is_file():
        raise ContentDeliveryError("file delivery source is missing or not a regular file")
    return _read_exact(source_path, source_path.stat().st_size)


def _directory_chunks(content_format: str, source_path: Path) -> Iterator[bytes]:
    """Validate a source-backed directory, then return its deterministic tar as chunks."""
    if content_format not in _DIRECTORY_FORMATS:
        raise ContentDeliveryError(f"directory format {content_format!r} has no deterministic materializer")
    if source_path.is_symlink() or not source_path.is_dir():
        raise ContentDeliveryError("directory delivery source is missing or not a directory")
    return _tar_chunks(_collect_regular_files(source_path))


def _tar_chunks(files: list[tuple[str, Path]]) -> Iterator[bytes]:
    """Emit the tar :mod:`tarfile` would write for ``files``, one block run at a time.

    Same header encoding, member padding, end-of-archive blocks and record
    padding as ``tarfile.open(mode="w")``, so payload digests are unchanged.
    """
    offset = 0
    for rel, abspath in files:
        size = abspath.stat().st_size
        header = _tar_info(rel, size).tobuf(tarfile.DEFAULT_FORMAT, tarfile.ENCODING, "surrogateescape")
        offset += len(header) + size + (-size % tarfile.BLOCKSIZE)
        yield from _tar_member(header, abspath, size)
    trailer = 2 * tarfile.BLOCKSIZE
    yield b"\0" * (trailer + (-(offset + trailer) % tarfile.RECORDSIZE))


def _tar_member(header: bytes, path: Path, size: int) -> Iterator[bytes]:
    """One member: its header, exactly ``size`` content bytes, then block padding."""
    yield header
    yield from _read_exact(path, size)
    yield b"\0" * (-size % tarfile.BLOCKSIZE)


def _tar_info(rel: str, size: int) -> tarfile.TarInfo:
    """Identity-normalized member header: no timestamps, owners or source modes."""
    info = tarfile.TarInfo(name=rel)
    info.size = size
    info.mtime = 0
    info.mode = _FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.type = tarfile.REGTYPE
    return info


def _collect_regular_files(root: Path) -> list[tuple[str, Path]]:
    """Return sorted (relative-posix, absolute) regular files under ``root``.

    Fails closed on any symlink or special file so a source tree cannot smuggle
    a link or device into the delivered payload.
    """
    resolved = root.resolve()
    collected: list[tuple[str, Path]] = []
    for path in sorted(resolved.rglob("*"), key=lambda entry: entry.relative_to(resolved).as_posix()):
        if path.is_symlink():
            raise ContentDeliveryError("directory delivery source contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ContentDeliveryError("directory delivery source contains a non-regular file")
        collected.append((path.relative_to(resolved).as_posix(), path))
    return collected


@dataclass(frozen=True)
class PayloadSource:
    """A deterministic delivery payload that can be re-read from the pack."""

    content_type: str
    content_format: str
    path: Path

    def chunks(self) -> Iterator[bytes]:
        return payload_chunks(content_type=self.content_type, content_format=self.content_format, source_path=self.path)


class _HashingReader(io.RawIOBase):
    """Readable view over payload chunks that hashes and counts what it serves."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._pending = b""
        self.hasher = hashlib.sha256()
        self.byte_count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: WriteableBuffer) -> int:
        while not self._pending:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._pending = chunk
        view = memoryview(buffer).cast("B")
        size = min(view.nbytes, len(self._pending))
        served, self._pending = self._pending[:size], self._pending[size:]
        view[:size] = served
        self.hasher.update(served)
        self.byte_count += size
        return size


def measure(source: PayloadSource) -> tuple[str, int]:
    """Digest and size of a payload computed by streaming it once (no buffering)."""
    hasher = hashlib.sha256()
    byte_count = 0
    for chunk in source.chunks():
        hasher.update(chunk)
        byte_count += len(chunk)
    return hasher.hexdigest(), byte_count


def promote(storage: ObjectStorage, bucket: str, key: str, source: PayloadSource, digest: str, byte_count: int) -> None:
    """Idempotently stream ``source`` to its content-addressed ``key``.

    The upload is hashed as it streams; if the bytes stored are not the bytes
    the key names (the source changed underneath), the object is removed and
    promotion fails closed rather than leaving a mislabeled object for reuse.
    """
    if storage.object_exists(bucket, key):
        return
    reader = _HashingReader(source.chunks())
    storage.upload_file(io.BufferedReader(reader, buffer_size=_CHUNK_BYTES), bucket, key, _OCTET_STREAM)
    if reader.hasher.hexdigest() != digest or reader.byte_count != byte_count:
        storage.delete_object(bucket, key)
        raise ContentDeliveryError("content delivery payload changed while it was promoted")
