"""Google Cloud Storage adapter implementing ObjectStorage protocol."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from shared.cloud.exceptions import CloudStorageError
from shared.cloud.gcp.base import import_google_module

logger = logging.getLogger(__name__)


class GCPObjectStorage:
    """GCS implementation of ObjectStorage protocol."""

    def _get_client(self) -> Any:
        try:
            storage = import_google_module("google.cloud.storage")
            return storage.Client()
        except ImportError as e:
            raise CloudStorageError("GCP storage support requires google-cloud-storage") from e

    def _signed_url_kwargs(self, client: Any) -> dict[str, Any]:
        """Build signed-URL kwargs that work with Workload Identity credentials.

        GKE Workload Identity and other metadata-backed credentials expose a
        service account email plus an OAuth access token, but not a local
        private key. google-cloud-storage can still generate V4 signed URLs via
        IAM signBlob when both values are supplied explicitly.
        """
        credentials = getattr(client, "_credentials", None)
        if credentials is None:
            return {}

        service_account_email = getattr(credentials, "service_account_email", None)
        if not service_account_email:
            return {}

        if (
            service_account_email == "default"
            or getattr(credentials, "token", None) is None
            or getattr(credentials, "expired", False)
        ):
            transport_requests = import_google_module("google.auth.transport.requests")
            credentials.refresh(transport_requests.Request())
            service_account_email = getattr(credentials, "service_account_email", None)

        access_token = getattr(credentials, "token", None)
        if not access_token:
            raise CloudStorageError("Failed to refresh GCP access token for signed URL generation")

        if not service_account_email or service_account_email == "default":
            raise CloudStorageError("Failed to resolve GCP service account email for signed URL generation")

        return {
            "version": "v4",
            "service_account_email": service_account_email,
            "access_token": access_token,
        }

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
            blob = client.bucket(bucket).blob(key)
            blob.upload_from_file(file_obj, content_type=content_type or None, rewind=True)
        except Exception as e:
            logger.error("upload_file: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to upload to GCS: {e}") from e
        logger.info("upload_file: success bucket=%s key=%s", bucket, key)

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.bucket(bucket).blob(key).delete()
        except Exception as e:
            logger.error("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete GCS object: {e}") from e
        logger.info("delete_object: success bucket=%s key=%s", bucket, key)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        logger.debug("head_object: bucket=%s key=%s", bucket, key)
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
            logger.error("head_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to head GCS object: {e}") from e

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
            blob = client.bucket(bucket).blob(key)
            signed_url_kwargs = self._signed_url_kwargs(client)
            return blob.generate_signed_url(
                expiration=timedelta(seconds=expires_in),
                method="PUT",
                content_type=content_type,
                **signed_url_kwargs,
            )
        except Exception as e:
            logger.error("generate_presigned_upload_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate GCS upload URL: {e}") from e

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int,
    ) -> str:
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            signed_url_kwargs = self._signed_url_kwargs(client)
            return blob.generate_signed_url(
                expiration=timedelta(seconds=expires_in),
                method="GET",
                **signed_url_kwargs,
            )
        except Exception as e:
            logger.error("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate GCS download URL: {e}") from e

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None:
        logger.debug("tag_object: bucket=%s key=%s tags=%s", bucket, key, tags)
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
            logger.error("tag_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to tag GCS object: {e}") from e
        logger.debug("tag_object: success bucket=%s key=%s", bucket, key)
