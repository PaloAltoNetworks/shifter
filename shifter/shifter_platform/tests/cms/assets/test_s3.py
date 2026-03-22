"""Unit tests for S3 service.

Tests verify that cms/assets/s3.py delegates to the ObjectStorage
abstraction and bridges CloudStorageError -> S3Error.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from cms.assets.s3 import (
    S3Error,
    delete_agent,
    generate_presigned_upload_url,
    get_s3_client,
    tag_s3_object,
    upload_agent,
    verify_s3_object_exists,
)
from shared.cloud.exceptions import CloudStorageError


@pytest.fixture
def mock_storage():
    """Return a MagicMock ObjectStorage wired into cms.assets.s3."""
    storage = MagicMock()
    with patch("cms.assets.s3.get_object_storage", return_value=storage):
        yield storage


class TestGetS3Client:
    @patch.dict("os.environ", {"AWS_ENDPOINT_URL": ""}, clear=False)
    @patch("boto3.client")
    def test_creates_client_with_region(self, mock_boto3_client, settings):
        settings.AWS_S3_REGION = "us-west-2"
        get_s3_client()
        mock_boto3_client.assert_called_once()
        call_kwargs = mock_boto3_client.call_args
        assert call_kwargs[0][0] == "s3"
        assert call_kwargs[1]["region_name"] == "us-west-2"
        assert call_kwargs[1]["endpoint_url"] == "https://s3.us-west-2.amazonaws.com"


class TestUploadAgent:
    def test_successful_upload(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"

        file_obj = io.BytesIO(b"test content")
        s3_key, sha256_hash, file_size = upload_agent(file_obj, 123, "agent.msi")

        assert s3_key.startswith("agents/123/")
        assert s3_key.endswith("_agent.msi")
        assert len(sha256_hash) == 64
        assert file_size == 12

        mock_storage.upload_file.assert_called_once()
        call_kwargs = mock_storage.upload_file.call_args
        assert call_kwargs[1]["bucket"] == "test-bucket"
        assert call_kwargs[1]["content_type"] == "application/octet-stream"

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        file_obj = io.BytesIO(b"test")

        with pytest.raises(S3Error) as exc:
            upload_agent(file_obj, 123, "agent.msi")
        assert "not configured" in str(exc.value)

    def test_raises_s3error_on_cloud_storage_error(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.upload_file.side_effect = CloudStorageError("Failed to upload to S3: boom")

        file_obj = io.BytesIO(b"test content")
        with pytest.raises(S3Error) as exc:
            upload_agent(file_obj, 123, "agent.msi")
        assert "Failed to upload" in str(exc.value)

    def test_calculates_correct_sha256(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"

        file_obj = io.BytesIO(b"hello")
        _, sha256_hash, _ = upload_agent(file_obj, 1, "test.msi")

        expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert sha256_hash == expected


class TestDeleteAgent:
    def test_successful_delete(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"

        delete_agent("agents/123/abc_test.msi")

        mock_storage.delete_object.assert_called_once_with(bucket="test-bucket", key="agents/123/abc_test.msi")

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""

        with pytest.raises(S3Error) as exc:
            delete_agent("some/key")
        assert "not configured" in str(exc.value)

    def test_raises_s3error_on_cloud_storage_error(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.delete_object.side_effect = CloudStorageError("Failed to delete from S3: boom")

        with pytest.raises(S3Error) as exc:
            delete_agent("some/key")
        assert "Failed to delete" in str(exc.value)


class TestGeneratePresignedUploadUrl:
    def test_successful_url_generation(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        settings.AGENT_UPLOAD_URL_EXPIRES = 900
        mock_storage.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"

        url, s3_key = generate_presigned_upload_url(123, "agent.msi")

        assert url == "https://s3.example.com/presigned"
        assert s3_key.startswith("agents/123/")
        mock_storage.generate_presigned_upload_url.assert_called_once()
        call_kwargs = mock_storage.generate_presigned_upload_url.call_args[1]
        assert call_kwargs["bucket"] == "test-bucket"
        assert call_kwargs["content_type"] == "application/octet-stream"
        assert call_kwargs["expires_in"] == 900

    def test_raises_s3error_on_cloud_storage_error(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        settings.AGENT_UPLOAD_URL_EXPIRES = 900
        mock_storage.generate_presigned_upload_url.side_effect = CloudStorageError("boom")

        with pytest.raises(S3Error):
            generate_presigned_upload_url(123, "agent.msi")


class TestVerifyS3ObjectExists:
    def test_successful_verify(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.head_object.return_value = {"content_length": 1024, "etag": "abc123"}

        size, etag = verify_s3_object_exists("agents/123/test.msi")

        assert size == 1024
        assert etag == "abc123"
        mock_storage.head_object.assert_called_once_with(bucket="test-bucket", key="agents/123/test.msi")

    def test_raises_s3error_on_not_found(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.head_object.side_effect = CloudStorageError("Failed to head S3 object: 404")

        with pytest.raises(S3Error, match="Object not found"):
            verify_s3_object_exists("agents/123/missing.msi")

    def test_raises_s3error_on_other_error(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.head_object.side_effect = CloudStorageError("Server error")

        with pytest.raises(S3Error, match="Server error"):
            verify_s3_object_exists("agents/123/test.msi")


class TestTagS3Object:
    def test_successful_tag(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"

        tag_s3_object("agents/123/test.msi", {"status": "verified"})

        mock_storage.tag_object.assert_called_once_with(
            bucket="test-bucket", key="agents/123/test.msi", tags={"status": "verified"}
        )

    def test_raises_s3error_on_cloud_storage_error(self, mock_storage, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_storage.tag_object.side_effect = CloudStorageError("Failed to tag")

        with pytest.raises(S3Error, match="Failed to tag"):
            tag_s3_object("agents/123/test.msi", {"status": "verified"})
