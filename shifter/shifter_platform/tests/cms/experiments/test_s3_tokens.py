"""Tests for upload token generation and verification.

Tests the HMAC token logic -- no real S3 calls needed.
"""

from unittest.mock import patch

import pytest

from cms.experiments.s3 import generate_upload_token, verify_upload_token


class TestUploadToken:
    @patch("cms.experiments.s3.settings")
    def test_roundtrip(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/abc_test.py",
            name="Test Script",
            filename="test.py",
            file_size=1024,
        )
        payload = verify_upload_token(token, user_id=1)
        assert payload["user_id"] == 1
        assert payload["s3_key"] == "scripts/1/abc_test.py"
        assert payload["name"] == "Test Script"
        assert payload["filename"] == "test.py"
        assert payload["file_size"] == 1024

    @patch("cms.experiments.s3.settings")
    def test_wrong_user_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        with pytest.raises(ValueError, match="user mismatch"):
            verify_upload_token(token, user_id=2)

    @patch("cms.experiments.s3.settings")
    def test_tampered_token_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(ValueError, match="signature"):
            verify_upload_token(tampered, user_id=1)

    @patch("cms.experiments.s3.settings")
    def test_invalid_format_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        with pytest.raises(ValueError, match="format"):
            verify_upload_token("no-dot-separator", user_id=1)

    @patch("cms.experiments.s3.settings")
    def test_expired_token_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = -1

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        with pytest.raises(ValueError, match="expired"):
            verify_upload_token(token, user_id=1)
