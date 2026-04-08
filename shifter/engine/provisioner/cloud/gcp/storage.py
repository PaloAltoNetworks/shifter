"""GCP Cloud Storage object storage adapter implementing ObjectStorage protocol."""

from __future__ import annotations

import datetime
import logging

from cloud.exceptions import CloudStorageError

from .base import BaseGCPAdapter

logger = logging.getLogger(__name__)


class GCPObjectStorage(BaseGCPAdapter):
    """Cloud Storage implementation of ObjectStorage protocol for provisioner."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import storage  # type: ignore[attr-defined]

        project = self._get_project()
        return storage.Client(project=project)

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
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
            return url
        except Exception as e:
            logger.error("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate signed URL: {e}") from e

    def object_exists(self, bucket: str, key: str) -> bool:
        logger.debug("object_exists: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            return blob.exists()
        except Exception as e:
            logger.error("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check object existence: {e}") from e

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.delete()
        except Exception as e:
            logger.error("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete object: {e}") from e
