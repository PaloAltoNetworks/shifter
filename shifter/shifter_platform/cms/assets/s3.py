"""S3 storage service for agent uploads."""

import hashlib
import logging
import os
import re
import uuid

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


class S3Error(Exception):
    """Raised when S3 operations fail."""

    pass


def get_s3_client():
    """Get boto3 S3 client configured for the region.

    Supports LocalStack via AWS_ENDPOINT_URL environment variable.
    """
    from botocore.config import Config

    # Use regional endpoint to avoid cross-region redirects that break CORS
    # For local dev, AWS_ENDPOINT_URL points to LocalStack
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint_url:
        endpoint_url = f"https://s3.{settings.AWS_S3_REGION}.amazonaws.com"

    config = Config(
        s3={"addressing_style": "virtual"},
        signature_version="s3v4",
    )
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION,
        endpoint_url=endpoint_url,
        config=config,
    )


def sanitize_s3_filename(filename: str) -> str:
    """
    Sanitize filename for S3 key generation (defense in depth).

    Removes path components, control characters, and limits length.
    Caller should have already used os.path.basename(), this is extra protection.
    """
    # Strip path components
    filename = os.path.basename(filename)

    # Remove null bytes and control characters
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)

    # Replace remaining path separators
    filename = filename.replace("/", "_").replace("\\", "_")

    # Remove leading dots (hidden files / traversal)
    filename = filename.lstrip(".")

    # Limit length (preserve extension)
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[: 200 - len(ext)] + ext

    return filename or "unnamed"


def upload_agent(file_obj, user_id: int, filename: str) -> tuple[str, str, int]:
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
    logger.debug("upload_agent: user_id=%s filename=%s", user_id, filename)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("upload_agent: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    # Generate unique key
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"agents/{user_id}/{unique_id}_{filename}"

    # Calculate SHA256 while reading file
    sha256 = hashlib.sha256()
    file_obj.seek(0)
    chunks = []
    while chunk := file_obj.read(8192):
        sha256.update(chunk)
        chunks.append(chunk)

    sha256_hash = sha256.hexdigest()
    file_size = sum(len(c) for c in chunks)

    # Reset for upload
    file_obj.seek(0)

    try:
        client = get_s3_client()
        client.upload_fileobj(
            file_obj,
            settings.AWS_S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={"ContentType": "application/octet-stream"},
        )
    except ClientError as e:
        logger.error("upload_agent: failed user_id=%s s3_key=%s error=%s", user_id, s3_key, e)
        raise S3Error(f"Failed to upload to S3: {e}") from e

    logger.info("upload_agent: success user_id=%s s3_key=%s size=%d", user_id, s3_key, file_size)
    return s3_key, sha256_hash, file_size


def delete_agent(s3_key: str) -> None:
    """
    Delete agent file from S3.

    Args:
        s3_key: S3 key of the file to delete

    Raises:
        S3Error: If delete fails
    """
    logger.debug("delete_agent: s3_key=%s", s3_key)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("delete_agent: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        client = get_s3_client()
        client.delete_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=s3_key)
    except ClientError as e:
        logger.error("delete_agent: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to delete from S3: {e}") from e  # nosec B608

    logger.info("delete_agent: success s3_key=%s", s3_key)


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
    logger.debug("generate_presigned_upload_url: user_id=%s filename=%s", user_id, filename)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("generate_presigned_upload_url: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    # Sanitize filename and generate unique key
    safe_filename = sanitize_s3_filename(filename)
    unique_id = uuid.uuid4().hex[:12]
    s3_key = f"agents/{user_id}/{unique_id}_{safe_filename}"

    try:
        client = get_s3_client()
        presigned_url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET_NAME,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.AGENT_UPLOAD_URL_EXPIRES,
        )
    except ClientError as e:
        logger.error("generate_presigned_upload_url: failed user_id=%s error=%s", user_id, e)
        raise S3Error(f"Failed to generate presigned URL: {e}") from e

    logger.debug("generate_presigned_upload_url: success user_id=%s s3_key=%s", user_id, s3_key)
    return presigned_url, s3_key


def verify_s3_object_exists(s3_key: str) -> tuple[int, str]:
    """
    Verify an S3 object exists and return its metadata.

    Args:
        s3_key: S3 object key

    Returns:
        Tuple of (file_size_bytes, etag)

    Raises:
        S3Error: If object doesn't exist or verification fails
    """
    logger.debug("verify_s3_object_exists: s3_key=%s", s3_key)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("verify_s3_object_exists: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        client = get_s3_client()
        response = client.head_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
        )
        size = response["ContentLength"]
        etag = response["ETag"].strip('"')
        logger.debug("verify_s3_object_exists: success s3_key=%s size=%d", s3_key, size)
        return size, etag
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.warning("verify_s3_object_exists: not found s3_key=%s", s3_key)
            raise S3Error(f"Object not found: {s3_key}") from e
        logger.error("verify_s3_object_exists: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to verify S3 object: {e}") from e


def tag_s3_object(s3_key: str, tags: dict[str, str]) -> None:
    """
    Add tags to an S3 object (used to mark uploads as completed).

    Args:
        s3_key: S3 object key
        tags: Dict of tag key-value pairs

    Raises:
        S3Error: If tagging fails
    """
    logger.debug("tag_s3_object: s3_key=%s tags=%s", s3_key, tags)

    if not settings.AWS_S3_BUCKET_NAME:
        logger.error("tag_s3_object: AWS_S3_BUCKET_NAME is not configured")
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        client = get_s3_client()
        client.put_object_tagging(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
            Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]},
        )
    except ClientError as e:
        logger.error("tag_s3_object: failed s3_key=%s error=%s", s3_key, e)
        raise S3Error(f"Failed to tag S3 object: {e}") from e

    logger.debug("tag_s3_object: success s3_key=%s", s3_key)
