"""Instance utilities tests for Shifter Engine.

Unit tests for instance utilities:
- SSH keypair generation (RSA 4096)
- S3 path validation for shell injection prevention
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the real functions we're testing
from components.instance import validate_s3_path
from utils.crypto import generate_ssh_keypair


class TestGenerateSshKeypair:
    """Tests for the generate_ssh_keypair function."""

    def test_returns_tuple_of_two_strings(self):
        """generate_ssh_keypair should return (private_key, public_key) tuple."""
        private_key, public_key = generate_ssh_keypair()

        assert isinstance(private_key, str)
        assert isinstance(public_key, str)

    def test_private_key_is_pem_format(self):
        """Private key should be in PEM format."""
        private_key, _ = generate_ssh_keypair()

        assert private_key.startswith("-----BEGIN RSA PRIVATE KEY-----")
        assert private_key.strip().endswith("-----END RSA PRIVATE KEY-----")

    def test_public_key_is_openssh_format(self):
        """Public key should be in OpenSSH format (ssh-rsa ...)."""
        _, public_key = generate_ssh_keypair()

        assert public_key.startswith("ssh-rsa ")

    def test_keys_are_unique_each_call(self):
        """Each call should generate a unique keypair."""
        key1_private, key1_public = generate_ssh_keypair()
        key2_private, key2_public = generate_ssh_keypair()

        assert key1_private != key2_private
        assert key1_public != key2_public

    def test_keypair_is_valid_rsa(self):
        """Generated keypair should be valid RSA."""
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key,
            load_ssh_public_key,
        )

        private_key_pem, public_key_openssh = generate_ssh_keypair()

        # Load and verify private key (RSA uses PEM format, not SSH format)
        private_key = load_pem_private_key(private_key_pem.encode(), password=None)
        assert private_key is not None

        # Verify public key can be loaded
        public_key = load_ssh_public_key(public_key_openssh.encode())
        assert public_key is not None

    def test_private_key_has_no_passphrase(self):
        """Private key should not be encrypted (no passphrase)."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key_pem, _ = generate_ssh_keypair()

        # This should succeed without a password
        private_key = load_pem_private_key(private_key_pem.encode(), password=None)
        assert private_key is not None


class TestValidateS3Path:
    """Tests for the validate_s3_path function."""

    def test_valid_simple_key(self):
        """Simple alphanumeric path should be valid."""
        assert validate_s3_path("agents/installer.sh") is True

    def test_valid_key_with_dashes(self):
        """Path with dashes should be valid."""
        assert validate_s3_path("my-bucket/my-key.tar.gz") is True

    def test_valid_key_with_underscores(self):
        """Path with underscores should be valid."""
        assert validate_s3_path("my_bucket/my_key.zip") is True

    def test_valid_key_with_dots(self):
        """Path with dots should be valid."""
        assert validate_s3_path("path/file.tar.gz") is True

    def test_valid_key_with_equals(self):
        """Path with equals sign should be valid (S3 metadata)."""
        assert validate_s3_path("path/file=value") is True

    def test_invalid_key_with_semicolon(self):
        """Semicolon (shell command separator) should be rejected."""
        assert validate_s3_path("; rm -rf /") is False

    def test_invalid_key_with_backtick(self):
        """Backtick (command substitution) should be rejected."""
        assert validate_s3_path("`whoami`") is False

    def test_invalid_key_with_dollar_paren(self):
        """Dollar-paren (command substitution) should be rejected."""
        assert validate_s3_path("$(command)") is False

    def test_invalid_key_with_pipe(self):
        """Pipe (command chaining) should be rejected."""
        assert validate_s3_path("file | cat") is False

    def test_invalid_key_with_ampersand(self):
        """Ampersand (command chaining) should be rejected."""
        assert validate_s3_path("file && rm") is False

    def test_invalid_key_with_newline(self):
        """Newline (command injection) should be rejected."""
        assert validate_s3_path("file\nrm -rf /") is False

    def test_invalid_key_with_space(self):
        """Space should be rejected (unsafe in shell)."""
        assert validate_s3_path("file with space") is False

    def test_empty_string_returns_false(self):
        """Empty string should return False."""
        assert validate_s3_path("") is False

    def test_valid_nested_path(self):
        """Deeply nested path should be valid."""
        assert validate_s3_path("a/b/c/d/e/file.tar.gz") is True
