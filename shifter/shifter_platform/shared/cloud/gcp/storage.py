"""GCP Cloud Storage adapter implementing ObjectStorage protocol.

Replaces AWS S3 for object storage operations used by Mission Control
(agent uploads, script uploads, presigned URLs).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from django.conf import settings

from shared.cloud.exceptions import CloudStorageError

logger = logging.getLogger(__name__)


class GCPObjectStorage:
    """Cloud Storage implementation of ObjectStorage protocol."""

    def _get_client(self) -> Any:
        from google.cloud import storage  # type: ignore[attr-defined]

        project: str | None = getattr(settings, "GCP_PROJECT_ID", None)
        return storage.Client(project=project)

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
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.upload_from_file(file_obj, content_type=content_type or None)
        except Exception as e:
            logger.error("upload_file: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to upload to Cloud Storage: {e}") from e
        logger.info("upload_file: success bucket=%s key=%s", bucket, key)

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.delete()
        except Exception as e:
            logger.error("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete from Cloud Storage: {e}") from e
        logger.info("delete_object: success bucket=%s key=%s", bucket, key)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        logger.debug("head_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.reload()
            return {
                "content_length": blob.size,
                "etag": blob.etag,
            }
        except Exception as e:
            logger.error("head_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to head Cloud Storage object: {e}") from e

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
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            url: str = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(seconds=expires_in),
                method="PUT",
                content_type=content_type,
            )
        except Exception as e:
            logger.error("generate_presigned_upload_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate signed upload URL: {e}") from e
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
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            url: str = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(seconds=expires_in),
                method="GET",
            )
        except Exception as e:
            logger.error("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate signed download URL: {e}") from e
        return url

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        logger.debug("tag_object: bucket=%s key=%s tags=%s", bucket, key, tags)
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.reload()
            metadata = blob.metadata or {}
            metadata.update(tags)
            blob.metadata = metadata
            blob.patch()
        except Exception as e:
            logger.error("tag_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to tag Cloud Storage object: {e}") from e
        logger.debug("tag_object: success bucket=%s key=%s", bucket, key)
