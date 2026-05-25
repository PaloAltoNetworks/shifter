"""Google Cloud Storage adapter implementing ObjectStorage protocol."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, BinaryIO

from shared.cloud.exceptions import CloudStorageError
from shared.cloud.gcp.base import import_google_module
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from google.cloud.storage import Client as GCSClient
else:
    GCSClient = Any

logger = logging.getLogger(__name__)


class GCPObjectStorage:
    """GCS implementation of ObjectStorage protocol."""

    @staticmethod
    def _get_client() -> GCSClient:
        try:
            storage = import_google_module("google.cloud.storage")
            return storage.Client()
        except ImportError as e:
            raise CloudStorageError("GCP storage support requires google-cloud-storage") from e

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
            blob = client.bucket(bucket).blob(key)
            blob.upload_from_file(file_obj, content_type=content_type or None, rewind=True)
        except Exception as e:
            logger.exception("upload_file: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to upload to GCS: {e}") from e
        logger.info("upload_file: success bucket=%s key=%s", bucket, safe_key)

    def delete_object(self, bucket: str, key: str) -> None:
        safe_key = safe_log_value(key)
        logger.debug("delete_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            client.bucket(bucket).blob(key).delete()
        except Exception as e:
            logger.exception("delete_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to delete GCS object: {e}") from e
        logger.info("delete_object: success bucket=%s key=%s", bucket, safe_key)

    def copy_object(self, bucket: str, src_key: str, dst_key: str) -> None:
        """Copy a blob within the same bucket using GCS rewrite."""
        safe_src = safe_log_value(src_key)
        safe_dst = safe_log_value(dst_key)
        logger.debug("copy_object: bucket=%s src=%s dst=%s", bucket, safe_src, safe_dst)
        try:
            client = self._get_client()
            source_bucket = client.bucket(bucket)
            source_blob = source_bucket.blob(src_key)
            source_bucket.copy_blob(source_blob, source_bucket, dst_key)
        except Exception as e:
            logger.exception(
                "copy_object: failed bucket=%s src=%s dst=%s",
                bucket,
                safe_src,
                safe_dst,
            )
            raise CloudStorageError(f"Failed to copy GCS object: {e}") from e
        logger.info("copy_object: success bucket=%s src=%s dst=%s", bucket, safe_src, safe_dst)

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return True iff the blob exists.

        Distinguishes a confirmed miss from any other error so callers can
        safely use this for "is the destination already occupied?" preflights.
        Other errors (auth, network) raise `CloudStorageError` so the caller
        fails closed.
        """
        safe_key = safe_log_value(key)
        logger.debug("object_exists: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).get_blob(key)
            return blob is not None
        except Exception as e:
            logger.exception("object_exists: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to test GCS object existence: {e}") from e

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        safe_key = safe_log_value(key)
        logger.debug("head_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).get_blob(key)
            if blob is None:
                raise CloudStorageError(f"GCS object not found: gs://{bucket}/{key}")
            return {
                "content_length": int(blob.size or 0),
                "etag": str(blob.etag or ""),
            }
        except CloudStorageError:
            raise
        except Exception as e:
            logger.exception("head_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to head GCS object: {e}") from e

    def read_object_header(self, bucket: str, key: str, max_bytes: int) -> bytes:
        """Read up to `max_bytes` from the start of the blob.

        GCS `download_as_bytes(start=, end=)` uses an inclusive `end`, so
        `max_bytes=512` corresponds to `end=511`.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_key = safe_log_value(key)
        logger.debug("read_object_header: bucket=%s key=%s max_bytes=%d", bucket, safe_key, max_bytes)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            body = blob.download_as_bytes(start=0, end=max_bytes - 1)
        except Exception as e:
            logger.exception(
                "read_object_header: failed bucket=%s key=%s error=%s",
                bucket,
                safe_key,
                safe_log_value(e),
            )
            raise CloudStorageError(f"Failed to read GCS object header: {e}") from e
        return body[:max_bytes]

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
            blob = client.bucket(bucket).blob(key)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="PUT",
                content_type=content_type,
            )
        except Exception as e:
            logger.exception(
                "generate_presigned_upload_url: failed bucket=%s key=%s",
                bucket,
                safe_key,
            )
            raise CloudStorageError(f"Failed to generate GCS upload URL: {e}") from e

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
            blob = client.bucket(bucket).blob(key)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="GET",
            )
        except Exception as e:
            logger.exception(
                "generate_presigned_download_url: failed bucket=%s key=%s",
                bucket,
                safe_key,
            )
            raise CloudStorageError(f"Failed to generate GCS download URL: {e}") from e

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        safe_key = safe_log_value(key)
        logger.debug("tag_object: bucket=%s key=%s tags=%s", bucket, safe_key, tags)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).get_blob(key)
            if blob is None:
                raise CloudStorageError(f"GCS object not found: gs://{bucket}/{key}")
            metadata = dict(blob.metadata or {})
            metadata.update(tags)
            blob.metadata = metadata
            blob.patch()
        except CloudStorageError:
            raise
        except Exception as e:
            logger.exception("tag_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to tag GCS object: {e}") from e
        logger.debug("tag_object: success bucket=%s key=%s", bucket, safe_key)
