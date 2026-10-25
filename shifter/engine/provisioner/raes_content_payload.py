"""Staging of source-backed RAES delivery payloads in the provisioner (ADR-032-R3, R9).

Downloads one binding's payload from the provisioner's own object storage
config into a local staging directory, bounded by the binding's exact byte
count, and verifies its digest and size before any guest is touched. Hashing
reads in bounded chunks, so memory stays constant for any payload size; the
staged file is then streamed to guests by ``raes_content_delivery``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tarfile
from collections.abc import Callable
from typing import Any

from shared.raes.content_delivery import ContentDeliveryError

from cloud.exceptions import CloudError
from cloud.types import ObjectStorage
from config import RaesContentDeliveryConfig
from log_redact import safe_log_value
from plans.raes_content_delivery import RaesContentPayload
from raes_delivery_contract import validated_binding

__all__ = [
    "RaesContentDeliveryError",
    "download_and_verify",
    "installed_tree_sha256",
    "sha256_file",
]

logger = logging.getLogger(__name__)

#: Read chunk size for hashing downloaded payloads and archive members.
_READ_CHUNK_BYTES = 1024 * 1024


class RaesContentDeliveryError(RuntimeError):
    """Value-free failure at the RAES content-delivery realization boundary."""


def sha256_file(path: str) -> str:
    """Return the hex sha256 of a file, read in bounded chunks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()


def installed_tree_sha256(tar_path: str) -> str:
    """Return the deterministic installed-tree digest for a directory payload.

    Computed over every regular file member's ``(sha256, name)`` pair, sorted by
    tar member name (the same sorted, POSIX-relative names
    ``shared.raes.content_delivery._materialize_directory`` writes), from the tar
    file already digest-verified against the binding in this same call --
    never from an untrusted or partially-extracted source. Members are hashed in
    bounded chunks, so memory stays constant for any archive size. A fresh
    in-guest readback that independently walks the *installed* destination tree
    and recomputes the identical manifest can therefore prove the extraction is
    byte-exact. Hashing the tar bytes themselves (the binding's own ``sha256``)
    only proves the *received* archive was intact before extraction -- it
    cannot detect an install that later dropped, altered, or misplaced a
    member, which is the defect this closes (ADR-034-R6).
    """
    hasher = hashlib.sha256()
    with tarfile.open(tar_path, mode="r:") as tar:
        members = sorted((member for member in tar.getmembers() if member.isfile()), key=lambda member: member.name)
        for member in members:
            member_hasher = hashlib.sha256()
            extracted = tar.extractfile(member)
            if extracted is not None:
                while chunk := extracted.read(_READ_CHUNK_BYTES):
                    member_hasher.update(chunk)
            hasher.update(f"{member_hasher.hexdigest()}  {member.name}\n".encode())
    return hasher.hexdigest()


def download_and_verify(
    storage_factory: Callable[[], ObjectStorage],
    config: RaesContentDeliveryConfig,
    content_type: str,
    raw_binding: dict[str, Any],
    staging_dir: str,
) -> RaesContentPayload:
    """Download one binding's payload into ``staging_dir`` and verify it.

    Fails closed before any guest is touched: a binding that fails the shared
    producer contract (:func:`validated_binding`), an unconfigured bucket, a
    staging filesystem without room for the payload, a downloaded-payload
    digest mismatch, or a downloaded size that disagrees with the binding's
    declared ``byte_count`` all raise here. There is no fixed size cap
    (ADR-032-R9): the download is bounded by the binding's exact byte count and
    bound to the object's identity (``head_object``), so a replacement
    mid-flight fails closed too. Memory stays constant: the payload is hashed
    from disk in chunks and later streamed to the guest from the same file.
    """
    if not config.bucket:
        raise RaesContentDeliveryError("RAES content delivery bucket is not configured")
    try:
        binding = validated_binding(raw_binding)
    except ContentDeliveryError:
        raise RaesContentDeliveryError("RAES content delivery binding is invalid") from None
    if shutil.disk_usage(staging_dir).free < binding.byte_count:
        raise RaesContentDeliveryError("RAES content delivery staging space is insufficient")

    storage = storage_factory()
    payload_path = os.path.join(staging_dir, "payload")
    try:
        identity = storage.head_object(config.bucket, binding.storage_key)
        storage.download_object(
            config.bucket,
            binding.storage_key,
            payload_path,
            # Storage requires a positive bound; a zero-byte payload is still
            # held to its exact size by the check below.
            max_bytes=max(binding.byte_count, 1),
            expected_identity=identity,
        )
        actual_sha256 = sha256_file(payload_path)
        actual_bytes = os.path.getsize(payload_path)
    except CloudError as exc:
        # logger.exception()/exc_info would attach exc's own traceback -- and
        # therefore exc's message, which provider adapters render with the
        # bucket/key baked in (see cloud/aws/storage.py, cloud/gcp/storage.py)
        # -- to the log record. Log only the bounded exception class name via
        # a plain (no exc_info) call, and raise a fresh value-free error
        # `from None` so neither the log nor the propagated exception carries
        # the storage key, bucket, or any other identity value.
        logger.error("RAES content delivery download failed: %s", safe_log_value(exc.__class__.__name__))  # NOSONAR
        raise RaesContentDeliveryError("RAES content delivery payload could not be retrieved") from None

    if actual_sha256 != binding.sha256:
        raise RaesContentDeliveryError("RAES content delivery downloaded payload digest mismatch")
    if actual_bytes != binding.byte_count:
        raise RaesContentDeliveryError("RAES content delivery downloaded payload size mismatch")
    tree_sha256 = installed_tree_sha256(payload_path) if content_type == "directory" else None
    return RaesContentPayload(
        path=payload_path,
        byte_count=binding.byte_count,
        sha256=binding.sha256,
        installed_tree_sha256=tree_sha256,
    )
