"""AWS S3 adapter implementing ObjectStorage protocol for provisioner."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.exceptions import CloudStorageError

logger = logging.getLogger(__name__)


class AWSObjectStorage:
    """S3 implementation of ObjectStorage protocol for provisioner."""

    def _get_client(self) -> Any:
        region: str = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            url: str = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except (ClientError, BotoCoreError) as e:
            logger.error("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate presigned URL: {e}") from e

    def object_exists(self, bucket: str, key: str) -> bool:
        logger.debug("object_exists: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            logger.error("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check object existence: {e}") from e
        except BotoCoreError as e:
            logger.error("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check object existence: {e}") from e

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.delete_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as e:
            logger.error("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete object: {e}") from e
