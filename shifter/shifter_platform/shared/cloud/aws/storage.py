"""AWS S3 adapter implementing ObjectStorage protocol.

The actual S3 logic will be extracted from cms/assets/s3.py and
cms/experiments/s3.py in Sub-Issue 2 (#812). This stub satisfies the
protocol interface so the factory can return it.
"""

from __future__ import annotations

import logging
import os
from typing import Any, BinaryIO

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudStorageError
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


class AWSObjectStorage:
    """S3 implementation of ObjectStorage protocol."""

    @staticmethod
    def _get_client() -> BaseClient:
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
        file_obj: BinaryIO,
        bucket: str,
        key: str,
        content_type: str = "",
    ) -> None:
        safe_key = safe_log_value(key)
        logger.debug("upload_file: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            extra_args: dict[str, str] = {}
            if content_type:
                extra_args["ContentType"] = content_type
            client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args)
        except (ClientError, BotoCoreError) as e:
            logger.exception("upload_file: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to upload to S3: {e}") from e
        logger.info("upload_file: success bucket=%s key=%s", bucket, safe_key)

    def delete_object(self, bucket: str, key: str) -> None:
        safe_key = safe_log_value(key)
        logger.debug("delete_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            client.delete_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as e:
            logger.exception("delete_object: failed bucket=%s key=%s", bucket, safe_key)
            msg = f"S3 delete failed: {e}"
            raise CloudStorageError(msg) from e
        logger.info("delete_object: success bucket=%s key=%s", bucket, safe_key)

    def copy_object(self, bucket: str, src_key: str, dst_key: str) -> None:
        """Server-side copy within the same bucket. No data flows through this process."""
        safe_src = safe_log_value(src_key)
        safe_dst = safe_log_value(dst_key)
        logger.debug("copy_object: bucket=%s src=%s dst=%s", bucket, safe_src, safe_dst)
        try:
            client = self._get_client()
            client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": src_key},
                Key=dst_key,
            )
        except (ClientError, BotoCoreError) as e:
            logger.exception(
                "copy_object: failed bucket=%s src=%s dst=%s",
                bucket,
                safe_src,
                safe_dst,
            )
            raise CloudStorageError(f"Failed to copy S3 object: {e}") from e
        logger.info("copy_object: success bucket=%s src=%s dst=%s", bucket, safe_src, safe_dst)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        safe_key = safe_log_value(key)
        logger.debug("head_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.head_object(Bucket=bucket, Key=key)
            return {
                "content_length": response["ContentLength"],
                "etag": response["ETag"].strip('"'),
            }
        except (ClientError, BotoCoreError) as e:
            logger.exception("head_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to head S3 object: {e}") from e

    def read_object_header(self, bucket: str, key: str, max_bytes: int) -> bytes:
        """Read up to `max_bytes` from the start of the object using a Range GET.

        Used by server-side upload inspection to validate magic bytes without
        downloading the whole object. The HTTP Range header is end-inclusive,
        so `max_bytes=512` requests `bytes=0-511`. The S3 ``StreamingBody``
        is closed in a ``finally`` block so concurrent finalization requests
        cannot leak botocore connections under load.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_key = safe_log_value(key)
        logger.debug("read_object_header: bucket=%s key=%s max_bytes=%d", bucket, safe_key, max_bytes)
        try:
            client = self._get_client()
            response = client.get_object(
                Bucket=bucket,
                Key=key,
                Range=f"bytes=0-{max_bytes - 1}",
            )
            stream = response["Body"]
            try:
                body = stream.read(max_bytes)
            finally:
                stream.close()
        except (ClientError, BotoCoreError) as e:
            logger.exception(
                "read_object_header: failed bucket=%s key=%s error=%s",
                bucket,
                safe_key,
                safe_log_value(e),
            )
            raise CloudStorageError(f"Failed to read S3 object header: {e}") from e
        return body[:max_bytes]

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return True iff the object exists.

        Distinguishes 404 (object not found → False) from any other error
        (auth failure, network, throttling → raises `CloudStorageError`).
        Callers must use this for "is the destination already occupied?"
        preflights — `head_object` raises on miss and is unsafe for that
        use because exception-as-boolean swallows real failures.
        """
        safe_key = safe_log_value(key)
        logger.debug("object_exists: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            status = (e.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            logger.exception(
                "object_exists: unexpected ClientError bucket=%s key=%s code=%s",
                bucket,
                safe_key,
                code,
            )
            raise CloudStorageError(f"Failed to test S3 object existence: {e}") from e
        except BotoCoreError as e:
            logger.exception("object_exists: BotoCoreError bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to test S3 object existence: {e}") from e

    def generate_presigned_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: int,
    ) -> str:
        safe_key = safe_log_value(key)
        logger.debug("generate_presigned_upload_url: bucket=%s key=%s", bucket, safe_key)
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
            logger.exception(
                "generate_presigned_upload_url: failed bucket=%s key=%s",
                bucket,
                safe_key,
            )
            raise CloudStorageError(f"Failed to generate presigned upload URL: {e}") from e
        return url

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int,
    ) -> str:
        safe_key = safe_log_value(key)
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, safe_key)
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
            logger.exception(
                "generate_presigned_download_url: failed bucket=%s key=%s",
                bucket,
                safe_key,
            )
            raise CloudStorageError(f"Failed to generate presigned download URL: {e}") from e
        return url

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        safe_key = safe_log_value(key)
        logger.debug("tag_object: bucket=%s key=%s tags=%s", bucket, safe_key, tags)
        try:
            client = self._get_client()
            client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]},
            )
        except (ClientError, BotoCoreError) as e:
            logger.exception("tag_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to tag S3 object: {e}") from e
        logger.debug("tag_object: success bucket=%s key=%s", bucket, safe_key)
