"""Behavior tests for GCPObjectStorage.read_object_header.

Drives the real ``GCPObjectStorage`` (including its real ``_get_client``, which
lazily imports ``google.cloud.storage`` and constructs a ``Client``) and mocks
only the google-cloud-storage boundary: ``google.cloud.storage.Client`` is
patched to return a fake client, instead of patching the first-party
``_get_client`` method directly.
"""

from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import PreconditionFailed

from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError
from shared.cloud.gcp.storage import GCPObjectStorage


class TestReadObjectHeader:
    def test_calls_download_with_inclusive_range_and_returns_bytes(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.download_as_bytes.return_value = b"\x50\x4b\x03\x04rest"
        fake_client.bucket.return_value.blob.return_value = fake_blob

        with patch("google.cloud.storage.Client", return_value=fake_client):
            result = storage.read_object_header("my-bucket", "my-key", max_bytes=512)

        assert result == b"\x50\x4b\x03\x04rest"
        fake_client.bucket.assert_called_once_with("my-bucket")
        fake_client.bucket.return_value.blob.assert_called_once_with("my-key")
        # GCS download_as_bytes(end=...) is inclusive, so requesting 512 bytes
        # means end=511.
        fake_blob.download_as_bytes.assert_called_once_with(start=0, end=511)

    def test_truncates_to_max_bytes_when_body_is_longer(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.download_as_bytes.return_value = b"y" * 2048
        fake_client.bucket.return_value.blob.return_value = fake_blob

        with patch("google.cloud.storage.Client", return_value=fake_client):
            result = storage.read_object_header("b", "k", max_bytes=64)

        assert len(result) <= 64

    def test_rejects_non_positive_max_bytes(self):
        storage = GCPObjectStorage()
        with pytest.raises(ValueError):
            storage.read_object_header("b", "k", max_bytes=0)
        with pytest.raises(ValueError):
            storage.read_object_header("b", "k", max_bytes=-1)

    def test_download_failure_maps_to_cloud_storage_error(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.download_as_bytes.side_effect = RuntimeError("transport error")
        fake_client.bucket.return_value.blob.return_value = fake_blob

        with patch("google.cloud.storage.Client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)


class TestHeadObjectIdentity:
    def test_exposes_generation_alongside_size_and_etag(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.size = 42
        fake_blob.etag = "etag-value"
        fake_blob.generation = 1720000000000001
        fake_client.bucket.return_value.get_blob.return_value = fake_blob

        with patch("google.cloud.storage.Client", return_value=fake_client):
            identity = storage.head_object("b", "k")

        assert identity == {
            "content_length": 42,
            "etag": "etag-value",
            "generation": 1720000000000001,
        }


class TestCopyObjectConditional:
    def test_passes_source_and_destination_generation_preconditions(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        source_bucket = fake_client.bucket.return_value

        with patch("google.cloud.storage.Client", return_value=fake_client):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "e", "generation": 777})

        kwargs = source_bucket.copy_blob.call_args.kwargs
        assert kwargs["if_source_generation_match"] == 777
        assert kwargs["if_generation_match"] == 0
        args = source_bucket.copy_blob.call_args.args
        assert args[2] == "dst"

    def test_precondition_failure_maps_to_object_precondition_error(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_client.bucket.return_value.copy_blob.side_effect = PreconditionFailed("generation mismatch")

        with (
            patch("google.cloud.storage.Client", return_value=fake_client),
            pytest.raises(ObjectPreconditionError),
        ):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"generation": 777})

    def test_other_failure_maps_to_cloud_storage_error(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_client.bucket.return_value.copy_blob.side_effect = RuntimeError("transport error")

        with (
            patch("google.cloud.storage.Client", return_value=fake_client),
            pytest.raises(CloudStorageError) as exc,
        ):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"generation": 777})
        assert not isinstance(exc.value, ObjectPreconditionError)

    def test_missing_source_generation_fails_closed(self):
        storage = GCPObjectStorage()
        with pytest.raises(CloudStorageError):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "e"})


class TestPresignedUrlIamSigning:
    """V4 signed-URL generation must sign via the IAM signBlob API under
    Workload Identity (no local private key) and locally when a key is present.
    """

    @staticmethod
    def _wi_credentials():
        # Compute/Workload-Identity creds: token only, no local signer.
        creds = MagicMock()
        creds.signer = None
        creds.signer_email = None
        creds.service_account_email = "portal@example.iam.gserviceaccount.com"
        creds.token = "wi-access-token"
        return creds

    @staticmethod
    def _key_credentials():
        # Service-account JSON-key creds: can sign locally.
        creds = MagicMock()
        creds.signer = MagicMock()
        creds.signer_email = "key@example.iam.gserviceaccount.com"
        return creds

    def test_upload_url_uses_iam_signblob_under_workload_identity(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.generate_signed_url.return_value = "https://signed/put"
        fake_client.bucket.return_value.blob.return_value = fake_blob
        creds = self._wi_credentials()

        with (
            patch("google.cloud.storage.Client", return_value=fake_client),
            patch("google.auth.default", return_value=(creds, "proj")),
        ):
            url = storage.generate_presigned_upload_url("b", "k", "application/octet-stream", 600)

        assert url == "https://signed/put"
        creds.refresh.assert_called_once()
        kwargs = fake_blob.generate_signed_url.call_args.kwargs
        assert kwargs["service_account_email"] == "portal@example.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "wi-access-token"
        assert kwargs["method"] == "PUT"

    def test_download_url_uses_iam_signblob_under_workload_identity(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.generate_signed_url.return_value = "https://signed/get"
        fake_client.bucket.return_value.blob.return_value = fake_blob
        creds = self._wi_credentials()

        with (
            patch("google.cloud.storage.Client", return_value=fake_client),
            patch("google.auth.default", return_value=(creds, "proj")),
        ):
            url = storage.generate_presigned_download_url("b", "k", 600)

        assert url == "https://signed/get"
        kwargs = fake_blob.generate_signed_url.call_args.kwargs
        assert kwargs["service_account_email"] == "portal@example.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "wi-access-token"
        assert kwargs["method"] == "GET"

    def test_local_key_credentials_sign_without_iam_kwargs(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.generate_signed_url.return_value = "https://signed/put"
        fake_client.bucket.return_value.blob.return_value = fake_blob
        creds = self._key_credentials()

        with (
            patch("google.cloud.storage.Client", return_value=fake_client),
            patch("google.auth.default", return_value=(creds, "proj")),
        ):
            storage.generate_presigned_upload_url("b", "k", "application/octet-stream", 600)

        creds.refresh.assert_not_called()
        kwargs = fake_blob.generate_signed_url.call_args.kwargs
        assert "service_account_email" not in kwargs
        assert "access_token" not in kwargs
