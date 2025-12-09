"""S3 storage service for agent uploads."""

import hashlib
import uuid

import boto3
from botocore.exceptions import ClientError
from django.conf import settings


class S3Error(Exception):
    """Raised when S3 operations fail."""

    pass


def get_s3_client():
    """Get boto3 S3 client configured for the region."""
    return boto3.client("s3", region_name=settings.AWS_S3_REGION)


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
    if not settings.AWS_S3_BUCKET_NAME:
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
        raise S3Error(f"Failed to upload to S3: {e}") from e

    return s3_key, sha256_hash, file_size


def delete_agent(s3_key: str) -> None:
    """
    Delete agent file from S3.

    Args:
        s3_key: S3 key of the file to delete

    Raises:
        S3Error: If delete fails
    """
    if not settings.AWS_S3_BUCKET_NAME:
        raise S3Error("AWS_S3_BUCKET_NAME is not configured")

    try:
        client = get_s3_client()
        client.delete_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=s3_key)
    except ClientError as e:
        raise S3Error(f"Failed to delete from S3: {e}") from e
