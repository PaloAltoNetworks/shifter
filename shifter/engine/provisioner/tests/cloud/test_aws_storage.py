"""Behavior tests for the provisioner-side AWSObjectStorage head_object/download_object.

Drives the real ``AWSObjectStorage`` (including its real ``_get_client`` region/
endpoint resolution) and mocks only the boto3 boundary: ``boto3.client`` is
patched to return a fake S3 client, instead of patching the first-party
``_get_client`` method directly. Mirrors
``shifter_platform/tests/shared/cloud/test_aws_storage.py``.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cloud.aws.storage import AWSObjectStorage
from cloud.exceptions import CloudStorageError, ObjectPreconditionError


def _make_client_error(code: str, op: str = "HeadObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, op)


def _precondition_error(op: str = "GetObject") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "PreconditionFailed", "Message": "At least one of the pre-conditions failed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        },
        op,
    )


class TestHeadObjectIdentity:
    def test_returns_content_length_and_unquoted_etag(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.head_object.return_value = {"ContentLength": 42, "ETag": '"deadbeef"'}

        with patch("boto3.client", return_value=fake_client):
            identity = storage.head_object("my-bucket", "my-key")

        assert identity == {"content_length": 42, "etag": "deadbeef"}
        fake_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="my-key")

    def test_client_error_maps_to_cloud_storage_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.head_object.side_effect = _make_client_error("404")

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.head_object("b", "k")

    def test_botocore_error_maps_to_cloud_storage_error(self):
        from botocore.exceptions import BotoCoreError

        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.head_object.side_effect = BotoCoreError()

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.head_object("b", "k")


class TestDownloadObject:
    def test_streams_full_object_to_dest_and_returns_identity(self, tmp_path):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.return_value = {"Body": BytesIO(b"packbytes"), "ETag": '"abc123"'}
        dest = tmp_path / "pkg.tar"

        with patch("boto3.client", return_value=fake_client):
            identity = storage.download_object(
                "my-bucket", "my-key", str(dest), max_bytes=1024, expected_identity={"etag": "abc123"}
            )

        assert dest.read_bytes() == b"packbytes"
        assert identity == {"content_length": len(b"packbytes"), "etag": "abc123"}
        kwargs = fake_client.get_object.call_args.kwargs
        assert kwargs["Bucket"] == "my-bucket"
        assert kwargs["Key"] == "my-key"
        # Bind the download to the validated object version (TOCTOU: an overwrite
        # after validation makes IfMatch fail).
        assert kwargs["IfMatch"] == "abc123"

    def test_no_expected_identity_omits_if_match(self, tmp_path):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.return_value = {"Body": BytesIO(b"data"), "ETag": '"e"'}
        dest = tmp_path / "pkg.tar"

        with patch("boto3.client", return_value=fake_client):
            storage.download_object("b", "k", str(dest), max_bytes=1024)

        assert "IfMatch" not in fake_client.get_object.call_args.kwargs

    def test_aborts_when_object_exceeds_max_bytes_without_leaving_oversize_file(self, tmp_path):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.return_value = {"Body": BytesIO(b"x" * 5000), "ETag": '"e"'}
        dest_path = tmp_path / "big.tar"
        dest = str(dest_path)

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.download_object("b", "k", dest, max_bytes=1024)

        # Fail closed BEFORE writing an over-size body: no oversize file left behind.
        assert not dest_path.exists() or dest_path.stat().st_size < 5000

    def test_precondition_failure_maps_to_object_precondition_error(self, tmp_path):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.side_effect = _precondition_error()
        dest = str(tmp_path / "x.tar")

        with patch("boto3.client", return_value=fake_client), pytest.raises(ObjectPreconditionError):
            storage.download_object("b", "k", dest, max_bytes=1024, expected_identity={"etag": "abc123"})

    def test_other_client_error_maps_to_cloud_storage_error(self, tmp_path):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.side_effect = _make_client_error("AccessDenied", "GetObject")
        dest = str(tmp_path / "x.tar")

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError) as exc:
            storage.download_object("b", "k", dest, max_bytes=1024)
        assert not isinstance(exc.value, ObjectPreconditionError)

    def test_rejects_non_positive_max_bytes(self, tmp_path):
        storage = AWSObjectStorage()
        dest = str(tmp_path / "x")
        with pytest.raises(ValueError):
            storage.download_object("b", "k", dest, max_bytes=0)
        with pytest.raises(ValueError):
            storage.download_object("b", "k", dest, max_bytes=-1)
