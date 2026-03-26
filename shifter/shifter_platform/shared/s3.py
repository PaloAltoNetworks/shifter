"""Shared S3 utilities.

Generic S3 helper functions used by multiple layers.
"""

import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)


def get_s3_client():
    """Get boto3 S3 client configured for the region.

    .. deprecated::
        New code should use ``shared.cloud.get_object_storage()`` instead.
        Kept for backward compatibility with code that needs the raw boto3 client.
    """
    import boto3
    from botocore.config import Config

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
    """Sanitize filename for S3 key generation (defense in depth).

    Removes path components, control characters, and limits length.
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
