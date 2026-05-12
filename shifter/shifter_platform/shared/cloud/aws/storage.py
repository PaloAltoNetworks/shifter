"""AWS S3 adapter implementing ObjectStorage protocol.

The actual S3 logic will be extracted from cms/assets/s3.py and
cms/experiments/s3.py in Sub-Issue 2 (#812). This stub satisfies the
protocol interface so the factory can return it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudStorageError

logger = logging.getLogger(__name__)


class AWSObjectStorage:
    """S3 implementation of ObjectStorage protocol."""

    def _get_client(self) -> Any:
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL")
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_S3_REGION", "us-east-2"))
        if not endpoint_url:
            endpoint_url = f"https://s3.{region}.amazonaws.com"

        config = Config(
            s3={"addressing_style": "virtual"},
            signature_version="s3v4",
        )
        return boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            config=config,
        )

    def upload_file(
        self,
        file_obj: Any,
        bucket: str,
        key: str,
        content_type: str = "",
    ) -> None:
        logger.debug("upload_file: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            extra_args: dict[str, str] = {}
            if content_type:
                extra_args["ContentType"] = content_type
            client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args)
        except (ClientError, BotoCoreError) as e:
            logger.error("upload_file: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to upload to S3: {e}") from e
        logger.info("upload_file: success bucket=%s key=%s", bucket, key)

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.delete_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as e:
            logger.error("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete from S3: {e}") from e  # nosec B608
        logger.info("delete_object: success bucket=%s key=%s", bucket, key)

    def copy_object(self, bucket: str, src_key: str, dst_key: str) -> None:
        """Server-side copy within the same bucket. No data flows through this process."""
        logger.debug("copy_object: bucket=%s src=%s dst=%s", bucket, src_key, dst_key)
        try:
            client = self._get_client()
            client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": src_key},
                Key=dst_key,
            )
        except (ClientError, BotoCoreError) as e:
            logger.error(
                "copy_object: failed bucket=%s src=%s dst=%s error=%s",
                bucket,
                src_key,
                dst_key,
                e,
            )
            raise CloudStorageError(f"Failed to copy S3 object: {e}") from e
        logger.info("copy_object: success bucket=%s src=%s dst=%s", bucket, src_key, dst_key)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        logger.debug("head_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.head_object(Bucket=bucket, Key=key)
            return {
                "content_length": response["ContentLength"],
                "etag": response["ETag"].strip('"'),
            }
        except (ClientError, BotoCoreError) as e:
            logger.error("head_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to head S3 object: {e}") from e

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return True iff the object exists.

        Distinguishes 404 (object not found → False) from any other error
        (auth failure, network, throttling → raises `CloudStorageError`).
        Callers must use this for "is the destination already occupied?"
        preflights — `head_object` raises on miss and is unsafe for that
        use because exception-as-boolean swallows real failures.
        """
        logger.debug("object_exists: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            status = (e.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            logger.error(
                "object_exists: unexpected ClientError bucket=%s key=%s code=%s",
                bucket,
                key,
                code,
            )
            raise CloudStorageError(f"Failed to test S3 object existence: {e}") from e
        except BotoCoreError as e:
            logger.error("object_exists: BotoCoreError bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to test S3 object existence: {e}") from e

    def generate_presigned_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: int,
    ) -> str:
        logger.debug("generate_presigned_upload_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            url: str = client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as e:
            logger.error("generate_presigned_upload_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate presigned upload URL: {e}") from e
        return url

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int,
    ) -> str:
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            url: str = client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as e:
            logger.error("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate presigned download URL: {e}") from e
        return url

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        logger.debug("tag_object: bucket=%s key=%s tags=%s", bucket, key, tags)
        try:
            client = self._get_client()
            client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]},
            )
        except (ClientError, BotoCoreError) as e:
            logger.error("tag_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to tag S3 object: {e}") from e
        logger.debug("tag_object: success bucket=%s key=%s", bucket, key)
