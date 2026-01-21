"""Secure upload token generation and verification.

Upload tokens are HMAC-signed tokens that authorize a user to complete
an upload after the file has been transferred to S3 via presigned URL.
"""

import base64
import hashlib
import hmac
import json
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)


def generate_upload_token(
    user_id: int,
    s3_key: str,
    name: str,
    filename: str,
    os_slug: str,
    file_size: int,
    agent_type: str = "xdr",
) -> str:
    """
    Generate a signed token for upload completion verification.

    Token contains upload metadata and expires after AGENT_UPLOAD_URL_EXPIRES seconds.

    Args:
        user_id: ID of the uploading user
        s3_key: S3 key where file will be uploaded
        name: User-provided agent name
        filename: Original filename
        os_slug: Operating system slug (windows/linux/macos)
        file_size: Expected file size in bytes
        agent_type: Type of agent (xdr, xdr_collector, cloud_identity_engine)

    Returns:
        Base64-encoded signed token string
    """
    payload = {
        "user_id": user_id,
        "s3_key": s3_key,
        "name": name,
        "filename": filename,
        "os_slug": os_slug,
        "file_size": file_size,
        "agent_type": agent_type,
        "expires_at": int(time.time()) + settings.AGENT_UPLOAD_URL_EXPIRES,
    }

    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()

    secret_key = settings.SECRET_KEY
    if secret_key is None:
        logger.error("generate_upload_token: SECRET_KEY is not configured")
        raise RuntimeError("SECRET_KEY is not configured")

    signature = hmac.new(
        secret_key.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()

    logger.debug("generate_upload_token: user_id=%s s3_key=%s", user_id, s3_key)
    return f"{payload_b64}.{signature}"


def verify_upload_token(token: str, user_id: int) -> dict:
    """
    Verify token signature and extract payload.

    Args:
        token: The upload token to verify
        user_id: ID of the user claiming the token (must match token)

    Returns:
        Dict containing token payload (s3_key, name, filename, os_slug, file_size)

    Raises:
        ValueError: If token is invalid, expired, or user mismatch
    """
    logger.debug("verify_upload_token: user_id=%s", user_id)

    try:
        payload_b64, signature = token.rsplit(".", 1)
    except ValueError as err:
        logger.warning("verify_upload_token: invalid format user_id=%s", user_id)
        raise ValueError("Invalid token format") from err

    secret_key = settings.SECRET_KEY
    if secret_key is None:
        logger.error("verify_upload_token: SECRET_KEY is not configured")
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
    except ValueError as err:
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
