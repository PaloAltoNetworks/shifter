"""Tests for upload token generation and verification.

Tests the HMAC token logic — no real S3 calls needed.
"""

import time

import pytest
from django.test import TestCase, override_settings

from experiments.s3 import generate_upload_token, verify_upload_token


@override_settings(SECRET_KEY="test-secret-key", SCRIPT_UPLOAD_URL_EXPIRES=600)
class UploadTokenTest(TestCase):
    def test_roundtrip(self):
        token = generate_upload_token(
            user_id=1, s3_key="scripts/1/abc_test.py",
            name="Test Script", filename="test.py", file_size=1024,
        )
        payload = verify_upload_token(token, user_id=1)
        assert payload["user_id"] == 1
        assert payload["s3_key"] == "scripts/1/abc_test.py"
        assert payload["name"] == "Test Script"
        assert payload["filename"] == "test.py"
        assert payload["file_size"] == 1024

    def test_wrong_user_raises(self):
        token = generate_upload_token(
            user_id=1, s3_key="scripts/1/x.py",
            name="Test", filename="x.py", file_size=100,
        )
        with pytest.raises(ValueError, match="user mismatch"):
            verify_upload_token(token, user_id=2)

    def test_tampered_token_raises(self):
        token = generate_upload_token(
            user_id=1, s3_key="scripts/1/x.py",
            name="Test", filename="x.py", file_size=100,
        )
        # Tamper with token
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(ValueError, match="signature"):
            verify_upload_token(tampered, user_id=1)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="format"):
            verify_upload_token("no-dot-separator", user_id=1)

    @override_settings(SECRET_KEY="test-secret-key", SCRIPT_UPLOAD_URL_EXPIRES=-1)
    def test_expired_token_raises(self):
        token = generate_upload_token(
            user_id=1, s3_key="scripts/1/x.py",
            name="Test", filename="x.py", file_size=100,
        )
        with pytest.raises(ValueError, match="expired"):
            verify_upload_token(token, user_id=1)
