"""Unit tests for S3 service."""

import io
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from mission_control.services.s3 import (
    S3Error,
    delete_agent,
    get_s3_client,
    upload_agent,
)


class TestGetS3Client:
    @patch("mission_control.services.s3.boto3")
    def test_creates_client_with_region(self, mock_boto3, settings):
        settings.AWS_S3_REGION = "us-west-2"
        get_s3_client()
        # Verify client is created with regional endpoint
        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args
        assert call_kwargs[0][0] == "s3"
        assert call_kwargs[1]["region_name"] == "us-west-2"
        assert call_kwargs[1]["endpoint_url"] == "https://s3.us-west-2.amazonaws.com"


class TestUploadAgent:
    @patch("mission_control.services.s3.get_s3_client")
    def test_successful_upload(self, mock_get_client, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        file_obj = io.BytesIO(b"test content")
        s3_key, sha256_hash, file_size = upload_agent(file_obj, 123, "agent.msi")

        assert s3_key.startswith("agents/123/")
        assert s3_key.endswith("_agent.msi")
        assert len(sha256_hash) == 64  # SHA256 hex digest length
        assert file_size == 12  # len("test content")

        mock_client.upload_fileobj.assert_called_once()
        call_args = mock_client.upload_fileobj.call_args
        assert call_args[0][1] == "test-bucket"
        assert call_args[1]["ExtraArgs"]["ContentType"] == "application/octet-stream"

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        file_obj = io.BytesIO(b"test")

        with pytest.raises(S3Error) as exc:
            upload_agent(file_obj, 123, "agent.msi")
        assert "not configured" in str(exc.value)

    @patch("mission_control.services.s3.get_s3_client")
    def test_raises_on_client_error(self, mock_get_client, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_client = MagicMock()
        mock_client.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Error"}}, "PutObject"
        )
        mock_get_client.return_value = mock_client

        file_obj = io.BytesIO(b"test content")
        with pytest.raises(S3Error) as exc:
            upload_agent(file_obj, 123, "agent.msi")
        assert "Failed to upload" in str(exc.value)

    @patch("mission_control.services.s3.get_s3_client")
    def test_calculates_correct_sha256(self, mock_get_client, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Known SHA256 for "hello"
        file_obj = io.BytesIO(b"hello")
        _, sha256_hash, _ = upload_agent(file_obj, 1, "test.msi")

        expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert sha256_hash == expected


class TestDeleteAgent:
    @patch("mission_control.services.s3.get_s3_client")
    def test_successful_delete(self, mock_get_client, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        delete_agent("agents/123/abc_test.msi")

        mock_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="agents/123/abc_test.msi")

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""

        with pytest.raises(S3Error) as exc:
            delete_agent("some/key")
        assert "not configured" in str(exc.value)

    @patch("mission_control.services.s3.get_s3_client")
    def test_raises_on_client_error(self, mock_get_client, settings):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Error"}}, "DeleteObject"
        )
        mock_get_client.return_value = mock_client

        with pytest.raises(S3Error) as exc:
            delete_agent("some/key")
        assert "Failed to delete" in str(exc.value)
