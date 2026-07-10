"""Behavior tests for ctf.s3 upload helpers."""

import hashlib
import io
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from ctf.s3 import CTFFileError, upload_challenge_file


@pytest.fixture
def s3_client(settings):
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        yield client


def _client_error(code: str, op: str, msg: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


class TestUploadChallengeFile:
    def test_streams_multi_chunk_upload(self, s3_client):
        payload = b"y" * 20_000
        s3_key, sha256_hash, file_size = upload_challenge_file(
            io.BytesIO(payload),
            event_id="evt-1",
            challenge_id="ch-1",
            filename="notes.txt",
        )

        assert s3_key.startswith("ctf-files/evt-1/ch-1/")
        assert file_size == len(payload)
        assert sha256_hash == hashlib.sha256(payload).hexdigest()
        s3_client.upload_fileobj.assert_called_once()
        call = s3_client.upload_fileobj.call_args
        assert call.args[1] == "test-bucket"
        assert call.kwargs["ExtraArgs"]["ContentType"] == "application/octet-stream"

    def test_raises_if_bucket_not_configured(self, settings):
        settings.AWS_S3_BUCKET_NAME = ""
        with pytest.raises(CTFFileError, match="not configured"):
            upload_challenge_file(io.BytesIO(b"x"), "e", "c", "f.txt")

    def test_raises_on_upload_failure(self, s3_client):
        s3_client.upload_fileobj.side_effect = _client_error("500", "PutObject")
        with pytest.raises(CTFFileError, match="Failed to upload"):
            upload_challenge_file(io.BytesIO(b"data"), "e", "c", "f.txt")
