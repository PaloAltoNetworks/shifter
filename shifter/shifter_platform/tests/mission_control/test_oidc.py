"""Tests for OIDC utilities."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from config.oidc import OIDCAuthenticationBackend, ShifterOIDCBackend, generate_username, provider_logout_url

User = get_user_model()


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


class TestProviderLogoutUrl:
    """Tests for provider_logout_url function."""

    def test_returns_cognito_logout_url(self, monkeypatch):
        """Returns properly formatted Cognito logout URL."""
        monkeypatch.setenv("OIDC_AUTH_DOMAIN", "https://auth.example.com")
        monkeypatch.setenv("OIDC_RP_CLIENT_ID", "test-client-id")

        request = MagicMock()
        request.is_secure.return_value = True
        request.get_host.return_value = "shifter.example.com"

        url = provider_logout_url(request)

        assert url.startswith("https://auth.example.com/logout?")
        assert "client_id=test-client-id" in url
        assert "logout_uri=https%3A%2F%2Fshifter.example.com%2F" in url

    def test_returns_http_logout_uri_when_not_secure(self, monkeypatch):
        """Uses http scheme when request is not secure."""
        monkeypatch.setenv("OIDC_AUTH_DOMAIN", "https://auth.example.com")
        monkeypatch.setenv("OIDC_RP_CLIENT_ID", "test-client-id")

        request = MagicMock()
        request.is_secure.return_value = False
        request.get_host.return_value = "localhost:8000"

        url = provider_logout_url(request)

        assert "logout_uri=http%3A%2F%2Flocalhost%3A8000%2F" in url

    def test_returns_home_when_auth_domain_missing(self, monkeypatch):
        """Returns '/' (home) when OIDC_AUTH_DOMAIN is not set (local dev)."""
        monkeypatch.delenv("OIDC_AUTH_DOMAIN", raising=False)
        monkeypatch.setenv("OIDC_RP_CLIENT_ID", "test-client-id")

        request = MagicMock()
        assert provider_logout_url(request) == "/"

    def test_returns_home_when_client_id_missing(self, monkeypatch):
        """Returns '/' (home) when OIDC_RP_CLIENT_ID is not set (local dev)."""
        monkeypatch.setenv("OIDC_AUTH_DOMAIN", "https://auth.example.com")
        monkeypatch.delenv("OIDC_RP_CLIENT_ID", raising=False)

        request = MagicMock()
        assert provider_logout_url(request) == "/"

    def test_returns_home_when_both_missing(self, monkeypatch):
        """Returns '/' (home) when both env vars are missing (local dev)."""
        monkeypatch.delenv("OIDC_AUTH_DOMAIN", raising=False)
        monkeypatch.delenv("OIDC_RP_CLIENT_ID", raising=False)

        request = MagicMock()
        assert provider_logout_url(request) == "/"


class TestShifterOIDCBackendBootstrapAdmin:
    """Tests for OIDC bootstrap staff/superuser elevation."""

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["admin@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["admin@example.com"],
    )
    def test_create_user_applies_bootstrap_admin_flags(self, db):
        """OIDC first login elevates configured bootstrap admin emails."""
        backend = ShifterOIDCBackend()
        user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
        )
        claims = {"email": "admin@example.com", "sub": "cognito-sub-123"}

        with (
            patch.object(OIDCAuthenticationBackend, "create_user", return_value=user),
            patch("config.oidc.update_cognito_sub"),
            patch("config.oidc.audit_auth_event"),
        ):
            created_user = backend.create_user(claims)

        assert created_user == user
        user.refresh_from_db()
        assert user.is_staff is True
        assert user.is_superuser is True

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["ops@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[],
    )
    def test_update_user_applies_bootstrap_staff_flags(self, db):
        """Returning OIDC users are elevated when bootstrap settings change."""
        backend = ShifterOIDCBackend()
        user = User.objects.create_user(
            username="ops@example.com",
            email="ops@example.com",
        )
        claims = {"email": "ops@example.com", "sub": "cognito-sub-456"}

        with (
            patch.object(OIDCAuthenticationBackend, "update_user", return_value=user),
            patch("config.oidc.update_cognito_sub"),
        ):
            updated_user = backend.update_user(user, claims)

        assert updated_user == user
        user.refresh_from_db()
        assert user.is_staff is True
        assert user.is_superuser is False


# =============================================================================
# ShifterOIDCBackend._update_cognito_sub
# =============================================================================


class TestShifterOIDCBackendUpdateCognitoSub:
    """Tests for ShifterOIDCBackend._update_cognito_sub method."""

    # -------------------------------------------------------------------------
    # Happy path
    # -------------------------------------------------------------------------

    def test_calls_update_cognito_sub_service(self):
        """_update_cognito_sub calls management service with user and sub."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {"sub": "abc-123-cognito-sub"}

        with patch("config.oidc.update_cognito_sub") as mock_update:
            backend._update_cognito_sub(user, claims)

        mock_update.assert_called_once_with(user, "abc-123-cognito-sub")

    def test_extracts_sub_from_claims(self):
        """_update_cognito_sub extracts sub value from claims dict."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {"sub": "xyz-789", "email": "test@example.com", "name": "Test"}

        with patch("config.oidc.update_cognito_sub") as mock_update:
            backend._update_cognito_sub(user, claims)

        mock_update.assert_called_once_with(user, "xyz-789")

    # -------------------------------------------------------------------------
    # Input validation - missing sub
    # -------------------------------------------------------------------------

    def test_logs_warning_when_sub_missing(self):
        """_update_cognito_sub logs warning when claims has no sub."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {"email": "test@example.com"}  # no sub

        with patch("config.oidc.logger") as mock_logger:
            backend._update_cognito_sub(user, claims)

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "missing 'sub'" in call_args[0][0]
        assert "test@example.com" in str(call_args)

    def test_does_not_call_service_when_sub_missing(self):
        """_update_cognito_sub does not call service when sub is missing."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {}  # no sub

        with patch("config.oidc.update_cognito_sub") as mock_update:
            backend._update_cognito_sub(user, claims)

        mock_update.assert_not_called()

    def test_does_not_call_service_when_sub_is_none(self):
        """_update_cognito_sub does not call service when sub is None."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {"sub": None}

        with patch("config.oidc.update_cognito_sub") as mock_update:
            backend._update_cognito_sub(user, claims)

        mock_update.assert_not_called()

    def test_does_not_call_service_when_sub_is_empty_string(self):
        """_update_cognito_sub does not call service when sub is empty."""
        backend = ShifterOIDCBackend()
        user = MagicMock()
        user.email = "test@example.com"
        claims = {"sub": ""}

        with patch("config.oidc.update_cognito_sub") as mock_update:
            backend._update_cognito_sub(user, claims)

        mock_update.assert_not_called()
