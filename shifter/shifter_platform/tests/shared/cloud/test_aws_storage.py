"""Behavior tests for AWSObjectStorage.read_object_header.

Drives the real ``AWSObjectStorage`` (including its real ``_get_client`` region/
endpoint/Config resolution) and mocks only the boto3 boundary: ``boto3.client``
is patched to return a fake S3 client, instead of patching the first-party
``_get_client`` method directly.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from shared.cloud.aws.storage import AWSObjectStorage
from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError


def _make_get_object_response(body: bytes):
    return {"Body": BytesIO(body)}


def _make_client_error(code: str, op: str = "GetObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, op)


class TestReadObjectHeader:
    def test_passes_correct_range_and_returns_body(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.return_value = _make_get_object_response(b"\x50\x4b\x03\x04rest")

        with patch("boto3.client", return_value=fake_client):
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

        with patch("boto3.client", return_value=fake_client):
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

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)

    def test_other_client_error_maps_to_cloud_storage_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.get_object.side_effect = _make_client_error("AccessDenied")

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError):
            storage.read_object_header("b", "k", max_bytes=512)


def _precondition_error(op: str = "CopyObject") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "PreconditionFailed", "Message": "At least one of the pre-conditions failed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        },
        op,
    )


class TestCopyObjectConditional:
    def test_passes_source_etag_precondition(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()

        with patch("boto3.client", return_value=fake_client):
            storage.copy_object_conditional(
                "my-bucket", "src", "dst", expected_identity={"content_length": 10, "etag": "abc123"}
            )

        kwargs = fake_client.copy_object.call_args.kwargs
        assert kwargs["Bucket"] == "my-bucket"
        assert kwargs["CopySource"] == {"Bucket": "my-bucket", "Key": "src"}
        assert kwargs["Key"] == "dst"
        assert kwargs["CopySourceIfMatch"] == "abc123"
        # Destination absence comes from the fresh server-minted install key, not
        # from a CopyObject destination precondition (not portable across
        # botocore versions / S3-compatible endpoints).
        assert "IfNoneMatch" not in kwargs

    def test_params_pass_real_botocore_validation(self):
        """Guard against unsupported SDK parameters that a MagicMock would hide.

        Drives the adapter through a real boto3 S3 client wrapped in a Stubber, so
        the exact request the adapter builds is validated/serialized against
        botocore's CopyObject model instead of being swallowed by a mock.
        """
        import boto3
        from botocore.stub import Stubber

        client = boto3.client("s3", region_name="us-east-2", aws_access_key_id="x", aws_secret_access_key="y")
        stubber = Stubber(client)
        stubber.add_response(
            "copy_object",
            {},
            {
                "Bucket": "b",
                "CopySource": {"Bucket": "b", "Key": "src"},
                "Key": "dst",
                "CopySourceIfMatch": "abc123",
            },
        )
        storage = AWSObjectStorage()
        with stubber, patch("boto3.client", return_value=client):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "abc123"})
        stubber.assert_no_pending_responses()

    def test_precondition_failure_maps_to_object_precondition_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.copy_object.side_effect = _precondition_error()

        with patch("boto3.client", return_value=fake_client), pytest.raises(ObjectPreconditionError):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "abc123"})

    def test_conflict_status_maps_to_object_precondition_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.copy_object.side_effect = ClientError(
            {"Error": {"Code": "ConditionalRequestConflict"}, "ResponseMetadata": {"HTTPStatusCode": 409}},
            "CopyObject",
        )

        with patch("boto3.client", return_value=fake_client), pytest.raises(ObjectPreconditionError):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "abc123"})

    def test_other_client_error_maps_to_cloud_storage_error(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.copy_object.side_effect = _make_client_error("AccessDenied", "CopyObject")

        with patch("boto3.client", return_value=fake_client), pytest.raises(CloudStorageError) as exc:
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"etag": "abc123"})
        assert not isinstance(exc.value, ObjectPreconditionError)

    def test_missing_source_etag_fails_closed(self):
        storage = AWSObjectStorage()
        with pytest.raises(CloudStorageError):
            storage.copy_object_conditional("b", "src", "dst", expected_identity={"content_length": 10})


class TestHeadObjectIdentity:
    def test_returns_content_length_and_unquoted_etag(self):
        storage = AWSObjectStorage()
        fake_client = MagicMock()
        fake_client.head_object.return_value = {"ContentLength": 42, "ETag": '"deadbeef"'}

        with patch("boto3.client", return_value=fake_client):
            identity = storage.head_object("b", "k")

        assert identity == {"content_length": 42, "etag": "deadbeef"}
