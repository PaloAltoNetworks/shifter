"""S3 storage service for agent uploads.

Delegates actual storage operations to the cloud abstraction layer
(``shared.cloud.get_object_storage``).  All public function signatures and
import paths are preserved for backward compatibility.
"""

import hashlib
import logging
import uuid
from typing import Any, BinaryIO

from django.conf import settings

from shared.cloud import get_object_storage
from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError
from shared.log_sanitize import safe_log_value

# ``get_s3_client`` and ``sanitize_s3_filename`` are re-exported from this
# module for backward compatibility: tests and older asset callers import them
# via ``cms.assets.s3``. The ``noqa: F401`` is
# required because flake8 cannot see those re-imports from outside the file.
from shared.s3 import (  # noqa: F401  # NOSONAR — re-exports, rationale above
    get_s3_client,
    sanitize_s3_filename,
)

# SonarCloud S1192: extracted duplicated string literals.
BUCKET_NOT_CONFIGURED_MSG = "AWS_S3_BUCKET_NAME is not configured"

logger = logging.getLogger(__name__)


class S3Error(Exception):
    """Raised when S3 operations fail."""

    pass


def upload_agent(file_obj: BinaryIO, user_id: int, filename: str) -> tuple[str, str, int]:
    """
    Upload agent file to S3.

    Args:
        file_obj: File-like object to upload
        user_id: ID of the user uploading
        filename: Original filename

    Returns:
        Tuple of (s3_key, sha256_hash, file_size_bytes)

    Raises:
        S3Error: If upload fails
    """
    logger.debug("upload_agent: user_id=%s filename=%s", user_id, safe_log_value(filename))

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("upload_agent: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    # Generate unique key
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"agents/{user_id}/{unique_id}_{filename}"

    # Calculate SHA256 while reading file (single pass; do not retain chunks).
    sha256 = hashlib.sha256()
    file_obj.seek(0)
    file_size = 0
    while chunk := file_obj.read(8192):
        sha256.update(chunk)
        file_size += len(chunk)

    sha256_hash = sha256.hexdigest()

    # Reset for upload
    file_obj.seek(0)

    try:
        storage = get_object_storage()
        storage.upload_file(
            file_obj,
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            content_type="application/octet-stream",
        )
    except CloudStorageError as e:
        logger.exception(
            "upload_agent: failed user_id=%s s3_key=%s",
            user_id,
            safe_log_value(s3_key),
        )
        raise S3Error(str(e)) from e

    logger.info("upload_agent: success user_id=%s s3_key=%s size=%d", user_id, safe_log_value(s3_key), file_size)
    return s3_key, sha256_hash, file_size


def delete_agent(s3_key: str) -> None:
    """
    Delete agent file from S3.

    Args:
        s3_key: S3 key of the file to delete

    Raises:
        S3Error: If delete fails
    """
    logger.debug("delete_agent: s3_key=%s", safe_log_value(s3_key))

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("delete_agent: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    try:
        storage = get_object_storage()
        storage.delete_object(bucket=settings.AWS_S3_BUCKET_NAME, key=s3_key)
    except CloudStorageError as e:
        logger.exception("delete_agent: failed s3_key=%s", safe_log_value(s3_key))
        raise S3Error(str(e)) from e

    logger.info("delete_agent: success s3_key=%s", safe_log_value(s3_key))


def generate_presigned_upload_url(
    user_id: int,
    filename: str,
    content_type: str = "application/octet-stream",
) -> tuple[str, str]:
    """
    Generate a presigned URL for direct S3 upload.

    Args:
        user_id: ID of the uploading user
        filename: Original filename (should be sanitized)
        content_type: MIME type of the file

    Returns:
        Tuple of (presigned_url, s3_key)

    Raises:
        S3Error: If URL generation fails
    """
    logger.debug("generate_presigned_upload_url: user_id=%s filename=%s", user_id, safe_log_value(filename))

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("generate_presigned_upload_url: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    # Sanitize filename and generate unique key
    safe_filename = sanitize_s3_filename(filename)
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"agents/{user_id}/{unique_id}_{safe_filename}"

    try:
        storage = get_object_storage()
        presigned_url = storage.generate_presigned_upload_url(
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            content_type=content_type,
            expires_in=settings.AGENT_UPLOAD_URL_EXPIRES,
        )
    except CloudStorageError as e:
        logger.exception("generate_presigned_upload_url: failed user_id=%s", user_id)
        raise S3Error(str(e)) from e

    logger.debug("generate_presigned_upload_url: success user_id=%s s3_key=%s", user_id, safe_log_value(s3_key))
    return presigned_url, s3_key


def verify_s3_object_exists(s3_key: str) -> dict[str, Any]:
    """
    Verify an S3 object exists and return its identity metadata.

    Returns the provider object-identity mapping (``content_length``, ``etag``,
    and provider-specific fields such as GCS ``generation``) so callers can both
    validate size and bind a later conditional operation to the exact version
    seen here. Treat the mapping as opaque and pass it straight to
    ``install_agent_object`` / ``copy_object_conditional``.

    Args:
        s3_key: S3 object key

    Returns:
        Object identity mapping (always includes ``content_length`` and ``etag``).

    Raises:
        S3Error: If object doesn't exist or verification fails
    """
    logger.debug("verify_s3_object_exists: s3_key=%s", safe_log_value(s3_key))

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("verify_s3_object_exists: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    try:
        storage = get_object_storage()
        metadata = storage.head_object(bucket=settings.AWS_S3_BUCKET_NAME, key=s3_key)
        logger.debug(
            "verify_s3_object_exists: success s3_key=%s size=%d",
            safe_log_value(s3_key),
            metadata["content_length"],
        )
        return metadata
    except CloudStorageError as e:
        if "not found" in str(e).lower() or "404" in str(e):
            logger.warning("verify_s3_object_exists: not found s3_key=%s", safe_log_value(s3_key))
            raise S3Error(f"Object not found: {s3_key}") from e
        logger.exception("verify_s3_object_exists: failed s3_key=%s", safe_log_value(s3_key))
        raise S3Error(str(e)) from e


def generate_install_key(user_id: int, filename: str) -> str:
    """Mint a fresh, server-controlled install key for a finalized upload.

    The staging key is the mutable presigned-PUT target; the install key is a
    distinct, freshly-generated destination that the client never sees and cannot
    pre-create, so the immutable-copy finalization has an unoccupied destination.
    """
    safe_filename = sanitize_s3_filename(filename)
    unique_id = uuid.uuid4().hex[:12]
    return f"agents/{user_id}/installed/{unique_id}_{safe_filename}"


def install_agent_object(src_key: str, dst_key: str, expected_identity: dict[str, Any]) -> None:
    """Conditionally copy a validated staging object to an immutable install key.

    Delegates to the provider ``copy_object_conditional``, which copies only if
    the source still matches ``expected_identity`` (captured at validation) and
    the destination is absent. A precondition failure means the validated bytes
    changed between check and use (or the destination is occupied) — surfaced as
    a distinct ``S3Error`` so the caller can treat it as a security signal.

    Raises:
        S3Error: On precondition failure or any other storage error.
    """
    logger.debug(
        "install_agent_object: src=%s dst=%s",
        safe_log_value(src_key),
        safe_log_value(dst_key),
    )

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("install_agent_object: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    try:
        storage = get_object_storage()
        storage.copy_object_conditional(
            bucket=settings.AWS_S3_BUCKET_NAME,
            src_key=src_key,
            dst_key=dst_key,
            expected_identity=expected_identity,
        )
    except ObjectPreconditionError as e:
        logger.warning(
            "install_agent_object: precondition failed src=%s dst=%s",
            safe_log_value(src_key),
            safe_log_value(dst_key),
        )
        raise S3Error("Upload changed during finalization") from e
    except CloudStorageError as e:
        logger.exception("install_agent_object: failed src=%s dst=%s", safe_log_value(src_key), safe_log_value(dst_key))
        raise S3Error(str(e)) from e

    logger.info("install_agent_object: success src=%s dst=%s", safe_log_value(src_key), safe_log_value(dst_key))


def read_agent_header(s3_key: str, max_bytes: int) -> bytes:
    """Read up to `max_bytes` from the start of an agent upload object.

    Used by `complete_upload` to inspect magic bytes server-side before
    finalization (issue #696). Bridges `CloudStorageError` to `S3Error`.

    Raises:
        S3Error: If the object cannot be read.
    """
    logger.debug("read_agent_header: s3_key=%s max_bytes=%d", safe_log_value(s3_key), max_bytes)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("read_agent_header: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    try:
        storage = get_object_storage()
        return storage.read_object_header(
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            max_bytes=max_bytes,
        )
    except CloudStorageError as e:
        logger.exception("read_agent_header: failed s3_key=%s error=%s", safe_log_value(s3_key), safe_log_value(e))
        raise S3Error(str(e)) from e


def tag_s3_object(s3_key: str, tags: dict[str, str]) -> None:
    """
    Add tags to an S3 object (used to mark uploads as completed).

    Args:
        s3_key: S3 object key
        tags: Dict of tag key-value pairs

    Raises:
        S3Error: If tagging fails
    """
    logger.debug("tag_s3_object: s3_key=%s tags=%s", safe_log_value(s3_key), tags)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("tag_s3_object: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error(BUCKET_NOT_CONFIGURED_MSG)

    try:
        storage = get_object_storage()
        storage.tag_object(bucket=settings.AWS_S3_BUCKET_NAME, key=s3_key, tags=tags)
    except CloudStorageError as e:
        logger.exception("tag_s3_object: failed s3_key=%s", safe_log_value(s3_key))
        raise S3Error(str(e)) from e

    logger.debug("tag_s3_object: success s3_key=%s", safe_log_value(s3_key))
