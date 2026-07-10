"""Behavior tests for the cms.assets.s3 helper.

These drive the real ``cms.assets.s3`` functions through the real
``shared.cloud`` AWS adapter down to the ``boto3`` S3 client, which is mocked at
that (genuine cloud) boundary instead of patching the first-party
``get_object_storage`` indirection. They verify the returned values, the boto3
call shape, and the ``ClientError`` -> ``CloudStorageError`` -> ``S3Error``
bridging.
"""

import hashlib
import io
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cms.assets.s3 import (
    S3Error,
    delete_agent,
    generate_install_key,
    generate_presigned_upload_url,
    get_s3_client,
    install_agent_object,
    tag_s3_object,
    upload_agent,
    verify_s3_object_exists,
)


@pytest.fixture
def s3_client(settings):
    """Patch ``boto3.client`` at the boundary with a deterministic S3 client."""
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        yield client


def _client_error(code: str, op: str, msg: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


class TestGetS3Client:
    @patch.dict("os.environ", {"AWS_ENDPOINT_URL": ""}, clear=False)
    @patch("boto3.client")
    def test_creates_client_with_region(self, mock_boto3_client, settings):
        settings.AWS_S3_REGION = "us-west-2"
        get_s3_client()
        mock_boto3_client.assert_called_once()
        call = mock_boto3_client.call_args
        assert call[0][0] == "s3"
        assert call[1]["region_name"] == "us-west-2"
        assert call[1]["endpoint_url"] == "https://s3.us-west-2.amazonaws.com"


class TestUploadAgent:
    def test_successful_upload(self, s3_client):
        s3_key, sha256_hash, file_size = upload_agent(io.BytesIO(b"test content"), 123, "agent.msi")

        assert s3_key.startswith("agents/123/")
        assert s3_key.endswith("_agent.msi")
        assert len(sha256_hash) == 64
        assert file_size == 12

        s3_client.upload_fileobj.assert_called_once()
        call = s3_client.upload_fileobj.call_args
        assert call.args[1] == "test-bucket"  # bucket positional
        assert call.kwargs["ExtraArgs"]["ContentType"] == "application/octet-stream"

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        with pytest.raises(S3Error, match="not configured"):
            upload_agent(io.BytesIO(b"test"), 123, "agent.msi")

    def test_raises_s3error_on_cloud_storage_error(self, s3_client):
        s3_client.upload_fileobj.side_effect = _client_error("500", "PutObject")
        with pytest.raises(S3Error, match="Failed to upload"):
            upload_agent(io.BytesIO(b"test content"), 123, "agent.msi")

    def test_calculates_correct_sha256(self, s3_client):
        _, sha256_hash, _ = upload_agent(io.BytesIO(b"hello"), 1, "test.msi")
        assert sha256_hash == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_streams_multi_chunk_upload_without_chunk_buffer(self, s3_client):
        """Hash and size over content larger than one read chunk (8192 bytes)."""
        payload = b"x" * 20_000
        _, sha256_hash, file_size = upload_agent(io.BytesIO(payload), 1, "big.msi")

        assert file_size == len(payload)
        assert sha256_hash == hashlib.sha256(payload).hexdigest()
        s3_client.upload_fileobj.assert_called_once()


class TestDeleteAgent:
    def test_successful_delete(self, s3_client):
        delete_agent("agents/123/abc_test.msi")
        s3_client.delete_object.assert_called_once()
        kwargs = s3_client.delete_object.call_args.kwargs
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == "agents/123/abc_test.msi"

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        with pytest.raises(S3Error, match="not configured"):
            delete_agent("some/key")

    def test_raises_s3error_on_cloud_storage_error(self, s3_client):
        s3_client.delete_object.side_effect = _client_error("500", "DeleteObject")
        with pytest.raises(S3Error, match="delete failed"):
            delete_agent("some/key")


class TestGeneratePresignedUploadUrl:
    def test_successful_url_generation(self, s3_client, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 900
        s3_client.generate_presigned_url.return_value = "https://s3.example.com/presigned"

        url, s3_key = generate_presigned_upload_url(123, "agent.msi")

        assert url == "https://s3.example.com/presigned"
        assert s3_key.startswith("agents/123/")
        call = s3_client.generate_presigned_url.call_args
        assert call.kwargs["ClientMethod"] == "put_object"
        assert call.kwargs["Params"]["Bucket"] == "test-bucket"
        assert call.kwargs["Params"]["ContentType"] == "application/octet-stream"
        assert call.kwargs["ExpiresIn"] == 900

    def test_raises_s3error_on_cloud_storage_error(self, s3_client, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 900
        s3_client.generate_presigned_url.side_effect = _client_error("500", "PutObject")
        with pytest.raises(S3Error):
            generate_presigned_upload_url(123, "agent.msi")


class TestVerifyS3ObjectExists:
    def test_successful_verify(self, s3_client):
        s3_client.head_object.return_value = {"ContentLength": 1024, "ETag": '"abc123"'}

        identity = verify_s3_object_exists("agents/123/test.msi")

        assert identity["content_length"] == 1024
        assert identity["etag"] == "abc123"  # adapter strips surrounding quotes
        kwargs = s3_client.head_object.call_args.kwargs
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == "agents/123/test.msi"

    def test_raises_s3error_on_not_found(self, s3_client):
        s3_client.head_object.side_effect = _client_error("404", "HeadObject", "Not Found")
        with pytest.raises(S3Error, match="Object not found"):
            verify_s3_object_exists("agents/123/missing.msi")

    def test_raises_s3error_on_other_error(self, s3_client):
        s3_client.head_object.side_effect = _client_error("500", "HeadObject", "Server error")
        with pytest.raises(S3Error, match="Server error"):
            verify_s3_object_exists("agents/123/test.msi")


class TestGenerateInstallKey:
    def test_distinct_from_staging_and_scoped_to_user(self):
        key = generate_install_key(123, "agent.msi")
        assert key.startswith("agents/123/installed/")
        assert key.endswith("_agent.msi")

    def test_two_calls_produce_distinct_keys(self):
        assert generate_install_key(1, "a.msi") != generate_install_key(1, "a.msi")

    def test_sanitizes_filename(self):
        key = generate_install_key(7, "../../etc/passwd")
        assert ".." not in key
        assert key.startswith("agents/7/installed/")


class TestInstallAgentObject:
    def test_delegates_conditional_copy_with_identity(self, s3_client):
        install_agent_object("agents/1/staging_a.msi", "agents/1/installed/x_a.msi", {"etag": "abc123"})

        kwargs = s3_client.copy_object.call_args.kwargs
        assert kwargs["CopySource"] == {"Bucket": "test-bucket", "Key": "agents/1/staging_a.msi"}
        assert kwargs["Key"] == "agents/1/installed/x_a.msi"
        assert kwargs["CopySourceIfMatch"] == "abc123"

    def test_precondition_failure_raises_distinct_s3error(self, s3_client):
        s3_client.copy_object.side_effect = ClientError(
            {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
            "CopyObject",
        )
        with pytest.raises(S3Error, match="changed during finalization"):
            install_agent_object("src", "dst", {"etag": "abc123"})

    def test_other_error_raises_s3error(self, s3_client):
        s3_client.copy_object.side_effect = _client_error("500", "CopyObject")
        with pytest.raises(S3Error):
            install_agent_object("src", "dst", {"etag": "abc123"})

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        with pytest.raises(S3Error, match="not configured"):
            install_agent_object("src", "dst", {"etag": "abc123"})


class TestTagS3Object:
    def test_successful_tag(self, s3_client):
        tag_s3_object("agents/123/test.msi", {"status": "verified"})

        kwargs = s3_client.put_object_tagging.call_args.kwargs
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == "agents/123/test.msi"
        assert kwargs["Tagging"] == {"TagSet": [{"Key": "status", "Value": "verified"}]}

    def test_raises_s3error_on_cloud_storage_error(self, s3_client):
        s3_client.put_object_tagging.side_effect = _client_error("500", "PutObjectTagging")
        with pytest.raises(S3Error, match="tag"):
            tag_s3_object("agents/123/test.msi", {"status": "verified"})
