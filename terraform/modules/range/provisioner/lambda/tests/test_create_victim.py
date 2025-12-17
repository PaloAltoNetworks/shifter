"""Tests for create_victim Lambda security functions."""

import pytest
import sys
import os

# Add handler module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "create_victim"))
from handler import validate_s3_path, get_user_data_script


class TestValidateS3Path:
    """Tests for S3 path validation."""

    def test_valid_bucket_name(self):
        assert validate_s3_path("my-bucket-name") is True

    def test_valid_bucket_with_dots(self):
        assert validate_s3_path("my.bucket.name") is True

    def test_valid_s3_key(self):
        assert validate_s3_path("agents/xdr/installer-v1.0.sh") is True

    def test_valid_s3_key_with_equals(self):
        assert validate_s3_path("path/to/file=value.txt") is True

    def test_valid_s3_key_underscores(self):
        assert validate_s3_path("path_to_file/name_here.bin") is True

    def test_invalid_shell_injection_semicolon(self):
        assert validate_s3_path("bucket; rm -rf /") is False

    def test_invalid_shell_injection_backticks(self):
        assert validate_s3_path("bucket`whoami`") is False

    def test_invalid_shell_injection_dollar(self):
        assert validate_s3_path("bucket$(whoami)") is False

    def test_invalid_shell_injection_pipe(self):
        assert validate_s3_path("bucket | cat /etc/passwd") is False

    def test_invalid_shell_injection_ampersand(self):
        assert validate_s3_path("bucket && rm -rf /") is False

    def test_invalid_shell_injection_quotes(self):
        assert validate_s3_path("bucket'injection") is False

    def test_invalid_shell_injection_double_quotes(self):
        assert validate_s3_path('bucket"injection') is False

    def test_invalid_newline(self):
        assert validate_s3_path("bucket\nrm -rf /") is False

    def test_invalid_space(self):
        assert validate_s3_path("bucket name") is False

    def test_empty_string(self):
        assert validate_s3_path("") is False


class TestGetUserDataScript:
    """Tests for user data script generation."""

    def test_valid_inputs_returns_base64(self):
        presigned_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc"
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test@example.com"
        result = get_user_data_script(
            presigned_url, "agents/installer.sh", public_key
        )
        # Should be base64 encoded
        import base64
        decoded = base64.b64decode(result).decode()
        assert "#!/bin/bash" in decoded
        assert "curl" in decoded
        assert presigned_url in decoded

    def test_rejects_invalid_key(self):
        presigned_url = "https://bucket.s3.amazonaws.com/key?sig=abc"
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test@example.com"
        with pytest.raises(ValueError, match="Invalid S3 key"):
            get_user_data_script(presigned_url, "key$(whoami).sh", public_key)

    def test_presigned_url_is_quoted(self):
        """Ensure presigned URL is single-quoted in script for extra safety."""
        presigned_url = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc"
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test@example.com"
        result = get_user_data_script(
            presigned_url, "my/key.sh", public_key
        )
        import base64
        decoded = base64.b64decode(result).decode()
        # URL should be in single quotes
        assert f"'{presigned_url}'" in decoded

    def test_includes_ssh_key(self):
        """Ensure SSH public key is included in authorized_keys."""
        presigned_url = "https://bucket.s3.amazonaws.com/key?sig=abc"
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test@example.com"
        result = get_user_data_script(
            presigned_url, "agents/installer.sh", public_key
        )
        import base64
        decoded = base64.b64decode(result).decode()
        assert public_key in decoded
        assert "authorized_keys" in decoded
