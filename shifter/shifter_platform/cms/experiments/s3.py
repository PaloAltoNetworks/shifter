"""S3 operations for experiment scripts and artifacts.

Follows the patterns established in cms/assets/s3.py and cms/assets/upload_token.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid

from botocore.exceptions import ClientError
from django.conf import settings

from cms.assets.s3 import S3Error, get_s3_client, sanitize_s3_filename

logger = logging.getLogger(__name__)


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

    safe_filename = sanitize_s3_filename(filename)
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"scripts/{user_id}/{unique_id}_{safe_filename}"

    try:
        client = get_s3_client()
        presigned_url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET_NAME,
                "Key": s3_key,
                "ContentType": "text/x-python",
            },
            ExpiresIn=settings.SCRIPT_UPLOAD_URL_EXPIRES,
        )
    except ClientError as e:
        logger.error("generate_script_upload_url: failed user_id=%s error=%s", user_id, e)
        raise S3Error(f"Failed to generate presigned URL: {e}") from e

    logger.debug("generate_script_upload_url: success user_id=%s s3_key=%s", user_id, s3_key)
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
        client = get_s3_client()
        url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        logger.error("generate_presigned_download_url: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to generate download URL: {e}") from e

    logger.debug("generate_presigned_download_url: success s3_key=%s", s3_key)
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
        client = get_s3_client()
        client.delete_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=s3_key)
    except ClientError as e:
        logger.error("delete_s3_object: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to delete from S3: {e}") from e  # nosec B608

    logger.info("delete_s3_object: success s3_key=%s", s3_key)


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
        client = get_s3_client()
        response = client.head_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=s3_key)
        size = response["ContentLength"]
        etag = response["ETag"].strip('"')
        logger.debug("verify_s3_object: success s3_key=%s size=%d", s3_key, size)
        return size, etag
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            logger.warning("verify_s3_object: not found s3_key=%s", s3_key)
            raise S3Error(f"Object not found: {s3_key}") from e
        logger.error("verify_s3_object: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to verify S3 object: {e}") from e


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
