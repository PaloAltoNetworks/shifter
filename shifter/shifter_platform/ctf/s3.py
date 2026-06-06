"""S3 storage operations for CTF challenge file attachments."""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse
from uuid import uuid4

from botocore.exceptions import ClientError
from django.conf import settings

from shared.log_sanitize import safe_log_value
from shared.s3 import get_s3_client, sanitize_s3_filename

logger = logging.getLogger(__name__)

# Constraints
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_FILES_PER_CHALLENGE = 10
ALLOWED_EXTENSIONS = {
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".7z",
    # Binaries / executables
    ".bin",
    ".elf",
    ".exe",
    ".dll",
    ".so",
    ".out",
    # Packet captures
    ".pcap",
    ".pcapng",
    ".cap",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".svg",
    # Documents
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    # Code / scripts
    ".py",
    ".js",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".rb",
    ".sh",
    ".ps1",
    # Crypto / certificates
    ".pem",
    ".crt",
    ".key",
    ".p12",
    ".pfx",
    # Disk / forensics
    ".img",
    ".iso",
    ".vmdk",
    ".dd",
    ".raw",
    ".mem",
    # Database
    ".db",
    ".sqlite",
    ".sql",
    # Other
    ".log",
    ".hex",
    ".wav",
    ".mp3",
}


class CTFFileError(Exception):
    """Raised when CTF file operations fail."""

    pass


def upload_challenge_file(
    file_obj,
    event_id: str,
    challenge_id: str,
    filename: str,
) -> tuple[str, str, int]:
    """Upload a challenge file to S3.

    Args:
        file_obj: File-like object to upload.
        event_id: UUID of the event (for S3 key path).
        challenge_id: UUID of the challenge (for S3 key path).
        filename: Original filename.

    Returns:
        Tuple of (s3_key, sha256_hash, file_size_bytes).

    Raises:
        CTFFileError: If upload fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        raise CTFFileError("AWS_S3_BUCKET_NAME is not configured")

    safe_filename = sanitize_s3_filename(filename)
    unique_id = uuid4().hex[:12]
    s3_key = f"ctf-files/{event_id}/{challenge_id}/{unique_id}_{safe_filename}"

    # Calculate SHA256 while reading
    sha256 = hashlib.sha256()
    file_obj.seek(0)
    chunks = []
    while True:
        chunk = file_obj.read(8192)
        if not chunk:
            break
        sha256.update(chunk)
        chunks.append(chunk)

    sha256_hash = sha256.hexdigest()
    file_size = sum(len(c) for c in chunks)

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
        logger.error("CTF file upload failed: s3_key=%s error=%s", safe_log_value(s3_key), e)
        raise CTFFileError(f"Failed to upload to S3: {e}") from e

    logger.info("CTF file uploaded: s3_key=%s size=%d", safe_log_value(s3_key), file_size)
    return s3_key, sha256_hash, file_size


def delete_challenge_file(s3_key: str) -> None:
    """Delete a challenge file from S3.

    Args:
        s3_key: S3 object key.

    Raises:
        CTFFileError: If delete fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        raise CTFFileError("AWS_S3_BUCKET_NAME is not configured")

    try:
        client = get_s3_client()
        client.delete_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=s3_key)
    except ClientError as e:
        logger.error("CTF file delete failed: s3_key=%s error=%s", safe_log_value(s3_key), e)
        raise CTFFileError(f"Failed to delete from S3: {e}") from e  # nosec B608

    logger.info("CTF file deleted: s3_key=%s", safe_log_value(s3_key))


def generate_download_url(s3_key: str, filename: str, expires_in: int = 300) -> str:
    """Generate a presigned download URL for a challenge file.

    Args:
        s3_key: S3 object key.
        filename: Filename for Content-Disposition header.
        expires_in: URL expiration in seconds (default 5 minutes).

    Returns:
        Presigned URL string.

    Raises:
        CTFFileError: If URL generation fails.
    """
    if not settings.AWS_S3_BUCKET_NAME:
        raise CTFFileError("AWS_S3_BUCKET_NAME is not configured")

    safe_filename = sanitize_s3_filename(filename)
    # Strip characters that could cause HTTP header injection (S5131).
    # Only allow alphanumeric, dash, underscore, dot, and space.
    safe_filename = re.sub(r"[^a-zA-Z0-9._\- ]", "_", safe_filename)

    try:
        client = get_s3_client()
        url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET_NAME,
                "Key": s3_key,
                "ResponseContentDisposition": f'attachment; filename="{safe_filename}"',
            },
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        logger.error("CTF download URL generation failed: s3_key=%s error=%s", safe_log_value(s3_key), e)
        raise CTFFileError(f"Failed to generate download URL: {e}") from e

    # Validate the presigned URL points to the expected S3 host
    _validate_s3_url(url)
    return url


def _validate_s3_url(url: str) -> None:
    """Validate that a presigned URL points to a trusted S3 endpoint.

    Prevents open-redirect if the URL were somehow tampered with.

    Raises:
        CTFFileError: If the URL host is not a trusted S3 endpoint.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Accept: s3.region.amazonaws.com, bucket.s3.region.amazonaws.com, localhost (dev)
    if host.endswith(".amazonaws.com") or host in ("localhost", "127.0.0.1"):
        return
    raise CTFFileError(f"Presigned URL has unexpected host: {host}")
