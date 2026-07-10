"""Google Cloud Storage adapter implementing ObjectStorage protocol."""

from __future__ import annotations

import logging
from datetime import timedelta

from cloud.exceptions import CloudStorageError
from cloud.gcp.base import import_google_module

logger = logging.getLogger(__name__)


class GCPObjectStorage:
    """GCS implementation of ObjectStorage protocol for the provisioner."""

    def _get_client(self):
        try:
            storage = import_google_module("google.cloud.storage")
            return storage.Client()
        except ImportError as e:
            raise CloudStorageError("GCP storage support requires google-cloud-storage") from e

    @staticmethod
    def _iam_signing_kwargs() -> dict[str, str]:
        """Return ``generate_signed_url`` kwargs for IAM-based V4 signing.

        Under Workload Identity the provisioner runs with compute-metadata
        credentials that carry only an access token and have no private key, so
        the client cannot sign a URL locally (it raises "you need a private key
        to sign credentials"). Passing ``service_account_email`` +
        ``access_token`` makes the client sign via the IAM credentials
        ``signBlob`` API instead, which only needs the service account to hold
        ``roles/iam.serviceAccountTokenCreator`` on itself.

        Credentials that can sign locally (a service-account JSON key) expose a
        ``signer`` and return an empty dict so the library keeps using the key.
        """
        google_auth = import_google_module("google.auth")
        auth_requests = import_google_module("google.auth.transport.requests")
        credentials, _ = google_auth.default()
        if getattr(credentials, "signer", None) is not None and getattr(credentials, "signer_email", None):
            return {}
        credentials.refresh(auth_requests.Request())
        return {
            "service_account_email": credentials.service_account_email,
            "access_token": credentials.token,
        }

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="GET",
                **self._iam_signing_kwargs(),
            )
        except Exception as e:
            logger.exception("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate GCS download URL: {e}") from e

    def object_exists(self, bucket: str, key: str) -> bool:
        logger.debug("object_exists: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            return client.bucket(bucket).blob(key).exists(client)
        except Exception as e:
            logger.exception("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check GCS object existence: {e}") from e

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.bucket(bucket).blob(key).delete()
        except Exception as e:
            logger.exception("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete GCS object: {e}") from e
