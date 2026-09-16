"""AWS S3 adapter implementing ObjectStorage protocol for provisioner."""

from __future__ import annotations

import logging
import os
from typing import Any, BinaryIO

from botocore.exceptions import BotoCoreError, ClientError

from cloud.aws.base import BaseAWSAdapter
from cloud.exceptions import CloudStorageError, ObjectPreconditionError
from log_redact import safe_log_value

logger = logging.getLogger(__name__)

#: Streaming chunk size for bounded full-object downloads.
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _stream_capped_to_file(stream: BinaryIO, dest_path: str, max_bytes: int) -> int:
    """Stream ``stream`` to ``dest_path`` in chunks, aborting past ``max_bytes``.

    Returns the number of bytes written. Raises ``CloudStorageError`` the moment
    the running total would exceed ``max_bytes``. The stream is always closed.
    """
    written = 0
    try:
        with open(dest_path, "wb") as handle:
            while True:
                chunk = stream.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise CloudStorageError(f"S3 object exceeds max_bytes={max_bytes}")
                handle.write(chunk)
    finally:
        stream.close()
    return written


class AWSObjectStorage(BaseAWSAdapter):
    """S3 implementation of ObjectStorage protocol for provisioner."""

    _service_name = "s3"

    @staticmethod
    def _owner_kwargs() -> dict[str, str]:
        """Return ``{"ExpectedBucketOwner": account_id}`` when the AWS account id is configured.

        AWS S3 honours ``ExpectedBucketOwner`` on every Get/Put/Head/Delete/Copy/
        Tagging request and fails the call with ``AccessDenied`` if the bucket's
        owner account does not match. This defends against bucket-squatting and
        against operator misconfiguration that swaps the deployment's bucket out
        from under us. Sourced from the ``AWS_S3_EXPECTED_BUCKET_OWNER`` env var
        (wired from the provisioner module's ``local.account_id`` at deploy time)
        so dev/test environments without a fixed account id continue to work.
        Mirrors ``shifter_platform/shared/cloud/aws/storage.py``.
        """
        owner = os.environ.get("AWS_S3_EXPECTED_BUCKET_OWNER", "")
        return {"ExpectedBucketOwner": owner} if owner else {}

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
        *,
        object_version: str | None = None,
    ) -> str:
        logger.debug("generate_presigned_download_url: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            params: dict[str, Any] = {"Bucket": bucket, "Key": key}
            if object_version is not None:
                # S3 object versions are opaque VersionId strings, carried through
                # unchanged (the S3 analog of a GCS generation).
                params["VersionId"] = object_version
            url: str = client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
            return url
        except (ClientError, BotoCoreError) as e:
            logger.exception("generate_presigned_download_url: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to generate presigned URL: {e}") from e

    def object_exists(self, bucket: str, key: str) -> bool:
        logger.debug("object_exists: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.head_object(Bucket=bucket, Key=key, **self._owner_kwargs())
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            logger.exception("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check object existence: {e}") from e
        except BotoCoreError as e:
            logger.exception("object_exists: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to check object existence: {e}") from e

    def delete_object(self, bucket: str, key: str) -> None:
        logger.debug("delete_object: bucket=%s key=%s", bucket, key)
        try:
            client = self._get_client()
            client.delete_object(Bucket=bucket, Key=key, **self._owner_kwargs())
        except (ClientError, BotoCoreError) as e:
            logger.exception("delete_object: failed bucket=%s key=%s error=%s", bucket, key, e)
            raise CloudStorageError(f"Failed to delete object: {e}") from e

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        safe_key = safe_log_value(key)
        logger.debug("head_object: bucket=%s key=%s", bucket, safe_key)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.head_object(Bucket=bucket, Key=key, **self._owner_kwargs())
            return {
                "content_length": response["ContentLength"],
                "etag": response["ETag"].strip('"'),
            }
        except (ClientError, BotoCoreError) as e:
            logger.exception("head_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to head S3 object: {e}") from e

    def download_object(
        self,
        bucket: str,
        key: str,
        dest_path: str,
        *,
        max_bytes: int,
        expected_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stream a full object to ``dest_path``, bounded by ``max_bytes``.

        Binds the GET to ``expected_identity["etag"]`` via ``IfMatch`` when
        supplied so an overwrite after validation fails closed (S3 returns
        ``412`` -> ``ObjectPreconditionError``). The body is streamed in chunks
        and aborts with ``CloudStorageError`` the moment the running total would
        exceed ``max_bytes`` (defense in depth against a mis-sized head). The
        streaming body is closed in a ``finally`` so a cap abort cannot leak a
        botocore connection.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_key = safe_log_value(key)
        logger.debug("download_object: bucket=%s key=%s max_bytes=%d", bucket, safe_key, max_bytes)
        get_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, **self._owner_kwargs()}
        etag = (expected_identity or {}).get("etag")
        if etag:
            get_kwargs["IfMatch"] = etag
        try:
            client = self._get_client()
            response = client.get_object(**get_kwargs)
            written = _stream_capped_to_file(response["Body"], dest_path, max_bytes)
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            status = (e.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if code == "PreconditionFailed" or status == 412:
                logger.warning("download_object: precondition failed bucket=%s key=%s", bucket, safe_key)
                raise ObjectPreconditionError("S3 object changed since validation (IfMatch failed)") from e
            logger.exception("download_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to download S3 object: {e}") from e
        except BotoCoreError as e:
            logger.exception("download_object: failed bucket=%s key=%s", bucket, safe_key)
            raise CloudStorageError(f"Failed to download S3 object: {e}") from e
        logger.info("download_object: success bucket=%s key=%s bytes=%d", bucket, safe_key, written)
        return {"content_length": written, "etag": response["ETag"].strip('"')}
