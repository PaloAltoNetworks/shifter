"""Tests for OIDC utilities."""

import pytest

from config.oidc import generate_username


class TestGenerateUsername:
    """Tests for generate_username function."""

    # Happy path tests
    def test_valid_corporate_email(self):
        """Standard corporate email passes through unchanged."""
        email = "jane.doe@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_valid_email_with_plus(self):
        """Email with + addressing is valid."""
        email = "jane+test@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_valid_email_with_dots(self):
        """Email with multiple dots is valid."""
        email = "jane.m.doe@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_valid_email_with_hyphen(self):
        """Email with hyphen is valid."""
        email = "jane-doe@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_valid_email_with_underscore(self):
        """Email with underscore is valid."""
        email = "jane_doe@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_valid_email_with_numbers(self):
        """Email with numbers is valid."""
        email = "jane123@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_max_length_exactly_150(self):
        """Email exactly at 150 chars is valid."""
        # 150 - len("@paloaltonetworks.com") = 150 - 21 = 129
        local_part = "a" * 129
        email = f"{local_part}@paloaltonetworks.com"
        assert len(email) == 150
        assert generate_username(email) == email

    # Sad path tests - length violations
    def test_email_exceeds_150_chars_raises(self):
        """Email over 150 chars raises ValueError."""
        local_part = "a" * 130
        email = f"{local_part}@paloaltonetworks.com"
        assert len(email) == 151

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "exceeds Django username limit" in str(exc_info.value)
        assert "Fix the Cognito pre-signup Lambda" in str(exc_info.value)

    def test_very_long_email_raises(self):
        """Very long email raises ValueError with truncated log message."""
        local_part = "a" * 200
        email = f"{local_part}@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "150 characters" in str(exc_info.value)

    # Sad path tests - character violations
    def test_email_with_exclamation_raises(self):
        """Email with ! (valid RFC 5321, invalid Django) raises ValueError."""
        email = "jane!doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_hash_raises(self):
        """Email with # raises ValueError."""
        email = "jane#doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_percent_raises(self):
        """Email with % raises ValueError."""
        email = "jane%doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_ampersand_raises(self):
        """Email with & raises ValueError."""
        email = "jane&doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_asterisk_raises(self):
        """Email with * raises ValueError."""
        email = "jane*doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_slash_raises(self):
        """Email with / raises ValueError."""
        email = "jane/doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_equals_raises(self):
        """Email with = raises ValueError."""
        email = "jane=doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_backtick_raises(self):
        """Email with ` raises ValueError."""
        email = "jane`doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_curly_braces_raises(self):
        """Email with {} raises ValueError."""
        email = "jane{doe}@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_pipe_raises(self):
        """Email with | raises ValueError."""
        email = "jane|doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    # Weird path tests - edge cases
    def test_empty_string_raises(self):
        """Empty email raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_username("")

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_whitespace_only_raises(self):
        """Whitespace-only email raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_username("   ")

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_space_raises(self):
        """Email containing space raises ValueError."""
        email = "jane doe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_newline_raises(self):
        """Email containing newline raises ValueError."""
        email = "jane\ndoe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_email_with_tab_raises(self):
        """Email containing tab raises ValueError."""
        email = "jane\tdoe@paloaltonetworks.com"

        with pytest.raises(ValueError) as exc_info:
            generate_username(email)

        assert "not allowed in Django usernames" in str(exc_info.value)

    def test_unicode_letters_allowed(self):
        """Unicode letters are allowed by Django's UnicodeUsernameValidator."""
        # \w in Python regex matches Unicode word characters
        email = "jäne@paloaltonetworks.com"
        assert generate_username(email) == email

    def test_email_at_boundary_149_chars(self):
        """Email at 149 chars (one under limit) is valid."""
        local_part = "a" * 128
        email = f"{local_part}@paloaltonetworks.com"
        assert len(email) == 149
        assert generate_username(email) == email

    def test_single_char_email(self):
        """Single character local part is valid."""
        email = "a@paloaltonetworks.com"
        assert generate_username(email) == email
