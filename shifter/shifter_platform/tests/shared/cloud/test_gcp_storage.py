"""Tests for GCPObjectStorage.read_object_header."""

from unittest.mock import MagicMock, patch

import pytest

from shared.cloud.exceptions import CloudStorageError
from shared.cloud.gcp.storage import GCPObjectStorage


class TestReadObjectHeader:
    def test_calls_download_with_inclusive_range_and_returns_bytes(self):
        storage = GCPObjectStorage()
        fake_client = MagicMock()
        fake_blob = MagicMock()
        fake_blob.download_as_bytes.return_value = b"\x50\x4b\x03\x04rest"
        fake_client.bucket.return_value.blob.return_value = fake_blob

        with patch.object(storage, "_get_client", return_value=fake_client):
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

        with patch.object(storage, "_get_client", return_value=fake_client):
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

        with patch.object(storage, "_get_client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)
