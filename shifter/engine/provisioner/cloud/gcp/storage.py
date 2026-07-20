"""Google Cloud Storage adapter implementing ObjectStorage protocol."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from cloud.exceptions import CloudStorageError, ObjectPreconditionError
from cloud.gcp.base import import_google_module
from log_redact import safe_log_value

if TYPE_CHECKING:
    from google.cloud.storage import Blob as GCSBlob
else:
    GCSBlob = Any

logger = logging.getLogger(__name__)


def _authoritative_size_and_generation(blob: GCSBlob, identity: dict[str, Any]) -> tuple[int | None, int | None]:
    """Return (size, generation) for ``blob``, reloading metadata when needed.

    Prefers the caller-supplied head identity; when it lacks ``content_length`` a
    single metadata reload provides the authoritative size (and the generation to
    bind the download to).
    """
    expected_len = identity.get("content_length")
    generation = identity.get("generation")
    if expected_len is None:
        blob.reload()
        expected_len = blob.size
        if generation is None:
            generation = blob.generation
    return expected_len, generation


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

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        safe_key = safe_log_value(key)
        logger.debug("head_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            blob = client.bucket(bucket).get_blob(key)
            if blob is None:
                raise CloudStorageError(f"GCS object not found: gs://{bucket}/{safe_key}")
            return {
                "content_length": int(blob.size or 0),
                "etag": str(blob.etag or ""),
                # Generation is GCS's strongest object identity -- monotonic and
                # never reused -- so it is the precondition of choice for
                # download_object.
                "generation": int(blob.generation or 0),
            }
        except CloudStorageError:
            raise
        except Exception as e:
            logger.exception("head_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to head GCS object: {e}") from e

    def download_object(
        self,
        bucket: str,
        key: str,
        dest_path: str,
        *,
        max_bytes: int,
        expected_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download a full blob to ``dest_path``, bounded by ``max_bytes``.

        Makes ``max_bytes`` a real transfer bound regardless of caller input: the
        authoritative object size is established BEFORE any bytes are written,
        from the head identity's ``content_length`` when supplied, otherwise via a
        single metadata ``reload``. An object larger than ``max_bytes`` is
        rejected before the transfer starts. The download is bound to the object
        generation (from the head identity or the reload) via
        ``if_generation_match`` so a replacement mid-flight fails closed
        (``PreconditionFailed`` -> ``ObjectPreconditionError``); the realized file
        size is re-checked afterward as defense in depth.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_key = safe_log_value(key)
        logger.debug("download_object: bucket=%s key=%s max_bytes=%d", bucket, safe_key, max_bytes)
        api_exceptions = import_google_module("google.api_core.exceptions")
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            # Establish the authoritative size (and generation) before any
            # transfer so the byte cap is enforced up front even when the caller
            # supplied no content_length.
            expected_len, generation = _authoritative_size_and_generation(blob, expected_identity or {})
            if expected_len is None or int(expected_len) > max_bytes:
                raise CloudStorageError(f"GCS object exceeds max_bytes={max_bytes}")
            download_kwargs = {"if_generation_match": int(generation)} if generation else {}
            with open(dest_path, "wb") as handle:
                blob.download_to_file(handle, **download_kwargs)
            written = os.path.getsize(dest_path)
            if written > max_bytes:
                raise CloudStorageError(f"GCS object exceeds max_bytes={max_bytes}")
        except api_exceptions.PreconditionFailed as e:
            logger.warning("download_object: precondition failed bucket=%s key=%s", bucket, safe_key)
            raise ObjectPreconditionError("GCS object changed since validation (generation mismatch)") from e
        except CloudStorageError:
            raise
        except Exception as e:
            logger.exception("download_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to download GCS object: {e}") from e
        logger.info("download_object: success bucket=%s key=%s bytes=%d", bucket, safe_key, written)
        return {"content_length": written, "etag": str(blob.etag or ""), "generation": int(blob.generation or 0)}
