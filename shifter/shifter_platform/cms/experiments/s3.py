"""S3 operations for experiment scripts and artifacts.

Follows the patterns established in cms/assets/s3.py and cms/assets/upload_token.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid

from django.conf import settings

from cms.assets.s3 import S3Error, sanitize_s3_filename
from shared.cloud import get_object_storage
from shared.cloud.exceptions import CloudStorageError
from shared.log_sanitize import safe_log

logger = logging.getLogger(__name__)

# Character set kept end-to-end aligned with
# cyberscript.script_context.S3KeySegment so a script upload that succeeds is
# guaranteed to satisfy the execution-time validator. Anything outside the
# whitelist collapses to '_'.
_SCRIPT_FILENAME_NORMALIZE = re.compile(r"[^A-Za-z0-9._=+-]+")


def _normalize_script_filename_segment(filename: str) -> str:
    """Normalize an uploaded script filename to a shell-safe S3 key segment.

    Wraps `sanitize_s3_filename` (which already strips path components,
    control characters, and leading dots) and then collapses any character
    outside the execution-time whitelist to `_`. Defuses any `..` sequence
    that survives the whitelist so the generated key always satisfies
    `cyberscript.script_context.S3KeySegment`. Empty results fall back to
    `unnamed.py` so the resulting key remains parseable.
    """
    base = sanitize_s3_filename(filename)
    normalized = _SCRIPT_FILENAME_NORMALIZE.sub("_", base)
    # Repeatedly collapse `..` until none remain, so cascades like `....` do
    # not survive a single .replace() pass.
    while ".." in normalized:
        normalized = normalized.replace("..", "_")
    normalized = normalized.strip("_")
    return normalized or "unnamed.py"


# Matches `cyberscript.script_context._MAX_S3_KEY` and the persisted
# `FileAsset.s3_key` column width. Truncation here keeps the normalized
# key short enough that both the validator and `asset.save()` will accept it.
_LEGACY_KEY_MAX_LEN = 500


def normalize_legacy_script_s3_key(key: str) -> str:
    """Normalize a legacy ScriptAsset.s3_key so it satisfies the execution validator.

    Normalizes each path segment individually so the key's `/` separators are
    preserved. Used by the 0002_normalize_legacy_script_s3_keys data migration
    to rewrite keys produced by the pre-#700 `sanitize_s3_filename` path.
    Truncates the final segment if the result exceeds the persisted column /
    validator cap (500 chars).
    """
    if not key:
        return "unnamed"
    segments: list[str] = []
    for segment in key.lstrip("/").split("/"):
        cleaned = _SCRIPT_FILENAME_NORMALIZE.sub("_", segment)
        while ".." in cleaned:
            cleaned = cleaned.replace("..", "_")
        cleaned = cleaned.strip("_")
        if cleaned:
            segments.append(cleaned)
    result = "/".join(segments) or "unnamed"
    if len(result) > _LEGACY_KEY_MAX_LEN:
        # Truncate the final segment so the overall key fits the cap.
        head, _, tail = result.rpartition("/")
        budget = _LEGACY_KEY_MAX_LEN - len(head) - (1 if head else 0)
        result = (head + "/" if head else "") + tail[:budget]
    return result


# ---------------------------------------------------------------------------
# Script S3 operations
# ---------------------------------------------------------------------------


def generate_script_upload_url(user_id: int, filename: str) -> tuple[str, str]:
    """Generate a presigned URL for direct S3 script upload.

    Args:
        user_id: ID of the uploading user.
        filename: Original filename (will be sanitized).

    Returns:
        Tuple of (presigned_url, s3_key).

    Raises:
        S3Error: If URL generation fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("generate_script_upload_url: AWS_S3_BUCKET_NAME not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    safe_filename = _normalize_script_filename_segment(filename)
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"scripts/{user_id}/{unique_id}_{safe_filename}"

    try:
        storage = get_object_storage()
        presigned_url = storage.generate_presigned_upload_url(
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            content_type="text/x-python",
            expires_in=settings.SCRIPT_UPLOAD_URL_EXPIRES,
        )
    except CloudStorageError as e:
        logger.error("generate_script_upload_url: failed user_id=%s error=%s", user_id, safe_log(str(e)))
        raise S3Error(str(e)) from e

    logger.debug("generate_script_upload_url: success user_id=%s s3_key=%s", user_id, safe_log(s3_key))
    return presigned_url, s3_key


def generate_presigned_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for downloading from S3.

    Args:
        s3_key: S3 object key.
        expires_in: URL expiry in seconds (default 1 hour).

    Returns:
        Presigned download URL.

    Raises:
        S3Error: If URL generation fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("generate_presigned_download_url: AWS_S3_BUCKET_NAME not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        storage = get_object_storage()
        url = storage.generate_presigned_download_url(
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            expires_in=expires_in,
        )
    except CloudStorageError as e:
        logger.error("generate_presigned_download_url: failed s3_key=%s error=%s", safe_log(s3_key), safe_log(str(e)))
        raise S3Error(str(e)) from e

    logger.debug("generate_presigned_download_url: success s3_key=%s", safe_log(s3_key))
    return url


def delete_s3_object(s3_key: str) -> None:
    """Delete an object from S3.

    Args:
        s3_key: S3 key of the object to delete.

    Raises:
        S3Error: If delete fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("delete_s3_object: AWS_S3_BUCKET_NAME not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        storage = get_object_storage()
        storage.delete_object(bucket=settings.AWS_S3_BUCKET_NAME, key=s3_key)
    except CloudStorageError as e:
        logger.error("delete_s3_object: failed s3_key=%s error=%s", safe_log(s3_key), safe_log(str(e)))
        raise S3Error(str(e)) from e

    logger.info("delete_s3_object: success s3_key=%s", safe_log(s3_key))


def read_script_header(s3_key: str, max_bytes: int) -> bytes:
    """Read up to `max_bytes` from the start of a script upload object.

    Bridges `CloudStorageError` to the `S3Error` family used by experiment
    services. Used by `complete_script_upload` to inspect server-side that
    the uploaded bytes are text rather than a binary file masquerading as a
    Python script (issue #696).
    """
    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("read_script_header: AWS_S3_BUCKET_NAME not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        storage = get_object_storage()
        return storage.read_object_header(
            bucket=settings.AWS_S3_BUCKET_NAME,
            key=s3_key,
            max_bytes=max_bytes,
        )
    except CloudStorageError as e:
        logger.error(
            "read_script_header: failed s3_key=%s error=%s",
            safe_log(s3_key),
            safe_log(str(e)),
        )
        raise S3Error(str(e)) from e


def verify_s3_object(s3_key: str) -> tuple[int, str]:
    """Verify an S3 object exists and return its metadata.

    Args:
        s3_key: S3 object key.

    Returns:
        Tuple of (file_size_bytes, etag).

    Raises:
        S3Error: If object doesn't exist or verification fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("verify_s3_object: AWS_S3_BUCKET_NAME not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        storage = get_object_storage()
        metadata = storage.head_object(bucket=settings.AWS_S3_BUCKET_NAME, key=s3_key)
        size = metadata["content_length"]
        etag = metadata["etag"]
        logger.debug("verify_s3_object: success s3_key=%s size=%d", safe_log(s3_key), size)
        return size, etag
    except CloudStorageError as e:
        if "not found" in str(e).lower() or "404" in str(e):
            logger.warning("verify_s3_object: not found s3_key=%s", safe_log(s3_key))
            raise S3Error(f"Object not found: {s3_key}") from e
        logger.error("verify_s3_object: failed s3_key=%s error=%s", safe_log(s3_key), safe_log(str(e)))
        raise S3Error(str(e)) from e


# ---------------------------------------------------------------------------
# Upload token (HMAC-signed) — same pattern as cms/assets/upload_token.py
# ---------------------------------------------------------------------------


def generate_upload_token(
    user_id: int,
    s3_key: str,
    name: str,
    filename: str,
    file_size: int,
) -> str:
    """Generate a signed token for script upload completion verification.

    Args:
        user_id: ID of the uploading user.
        s3_key: S3 key where file will be uploaded.
        name: User-provided script name.
        filename: Original filename.
        file_size: Expected file size in bytes.

    Returns:
        Base64-encoded signed token string.

    Raises:
        RuntimeError: If SECRET_KEY is not configured.
    """
    payload = {
        "user_id": user_id,
        "s3_key": s3_key,
        "name": name,
        "filename": filename,
        "file_size": file_size,
        "expires_at": int(time.time()) + settings.SCRIPT_UPLOAD_URL_EXPIRES,
    }

    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()

    secret_key = settings.SECRET_KEY
    if secret_key is None:
        logger.error("generate_upload_token: SECRET_KEY not configured")
        raise RuntimeError("SECRET_KEY is not configured")

    signature = hmac.new(
        secret_key.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()

    logger.debug("generate_upload_token: user_id=%s s3_key=%s", user_id, s3_key)
    return f"{payload_b64}.{signature}"


def verify_upload_token(token: str, user_id: int) -> dict:
    """Verify token signature and extract payload.

    Args:
        token: The upload token to verify.
        user_id: ID of the user claiming the token.

    Returns:
        Dict containing token payload.

    Raises:
        ValueError: If token is invalid, expired, or user mismatch.
    """
    logger.debug("verify_upload_token: user_id=%s", user_id)

    try:
        payload_b64, signature = token.rsplit(".", 1)
    except ValueError as err:
        logger.warning("verify_upload_token: invalid format user_id=%s", user_id)
        raise ValueError("Invalid token format") from err

    secret_key = settings.SECRET_KEY
    if secret_key is None:
        logger.error("verify_upload_token: SECRET_KEY not configured")
        raise RuntimeError("SECRET_KEY is not configured")

    expected_sig = hmac.new(
        secret_key.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        logger.warning("verify_upload_token: invalid signature user_id=%s", user_id)
        raise ValueError("Invalid token signature")

    try:
        payload_json = base64.urlsafe_b64decode(payload_b64).decode()
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError) as err:
        logger.warning("verify_upload_token: invalid payload user_id=%s", user_id)
        raise ValueError("Invalid token payload") from err

    if payload.get("user_id") != user_id:
        logger.warning(
            "verify_upload_token: user mismatch token_user=%s request_user=%s",
            payload.get("user_id"),
            user_id,
        )
        raise ValueError("Token user mismatch")

    if time.time() > payload.get("expires_at", 0):
        logger.warning("verify_upload_token: expired user_id=%s", user_id)
        raise ValueError("Token expired")

    logger.debug("verify_upload_token: success user_id=%s s3_key=%s", user_id, payload.get("s3_key"))
    return payload
