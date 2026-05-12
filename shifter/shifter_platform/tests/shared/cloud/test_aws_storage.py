"""Tests for AWSObjectStorage.read_object_header."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from shared.cloud.aws.storage import AWSObjectStorage
from shared.cloud.exceptions import CloudStorageError


def _make_get_object_response(body: bytes):
    return {"Body": BytesIO(body)}


def _make_client_error(code: str, op: str = "GetObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, op)


class TestReadObjectHeader:
    def test_passes_correct_range_and_returns_body(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.return_value = _make_get_object_response(b"\x50\x4b\x03\x04rest")

        with patch.object(storage, "_get_client", return_value=fake_client):
            result = storage.read_object_header("my-bucket", "my-key", max_bytes=512)

        assert result == b"\x50\x4b\x03\x04rest"
        fake_client.get_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="my-key",
            Range="bytes=0-511",
        )

    def test_truncates_to_max_bytes_when_body_is_longer(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        # S3 in real life respects Range so won't return more than asked, but the
        # adapter must still tolerate a longer body and cap it.
        fake_client.get_object.return_value = _make_get_object_response(b"x" * 2048)

        with patch.object(storage, "_get_client", return_value=fake_client):
            result = storage.read_object_header("b", "k", max_bytes=128)

        assert len(result) <= 128

    def test_rejects_non_positive_max_bytes(self):
        storage = AWSObjectStorage()
        with pytest.raises(ValueError):
            storage.read_object_header("b", "k", max_bytes=0)
        with pytest.raises(ValueError):
            storage.read_object_header("b", "k", max_bytes=-1)

    def test_404_maps_to_cloud_storage_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.side_effect = _make_client_error("NoSuchKey")

        with patch.object(storage, "_get_client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)

    def test_other_client_error_maps_to_cloud_storage_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.side_effect = _make_client_error("AccessDenied")

        with patch.object(storage, "_get_client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)
