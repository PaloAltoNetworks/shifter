"""Tests for OIDC utilities."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.test import override_settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from config.oidc import ShifterOIDCBackend, provider_logout_url
from config.username import generate_username
from management.services import get_user_profile
from risk_register.models import AuditLog

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


@pytest.mark.django_db
class TestShifterOIDCBackendBootstrapAdmin:
    """OIDC bootstrap staff/superuser elevation, driven through the real backend.

    Drives the real ``create_user`` / ``update_user`` (the mozilla base really
    creates/updates the Django user from claims), the real
    ``apply_bootstrap_admin_flags``, the real ``update_cognito_sub`` management
    service, and the real ``audit_auth_event`` — asserting persisted state
    (flags, profile, audit row) instead of patching them.
    """

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["admin@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["admin@example.com"],
    )
    def test_create_user_applies_bootstrap_admin_flags(self):
        """OIDC first login elevates configured bootstrap admin emails."""
        backend = ShifterOIDCBackend()
        claims = {"email": "admin@example.com", "sub": "cognito-sub-123"}

        created_user = backend.create_user(claims)

        created_user.refresh_from_db()
        assert created_user.email == "admin@example.com"
        assert created_user.is_staff is True
        assert created_user.is_superuser is True
        # cognito_sub persisted via the real management service.
        assert get_user_profile(created_user).cognito_sub == "cognito-sub-123"
        # New-user audit row written via the real audit service.
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.USER, action=AuditLog.Action.CREATE, actor_type=AuditLog.ActorType.COGNITO
        ).exists()

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["ops@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[],
    )
    def test_update_user_applies_bootstrap_staff_flags(self):
        """Returning OIDC users are elevated when bootstrap settings change."""
        backend = ShifterOIDCBackend()
        user = User.objects.create_user(username="ops@example.com", email="ops@example.com")
        claims = {"email": "ops@example.com", "sub": "cognito-sub-456"}

        updated_user = backend.update_user(user, claims)

        updated_user.refresh_from_db()
        assert updated_user.is_staff is True
        assert updated_user.is_superuser is False
        assert get_user_profile(updated_user).cognito_sub == "cognito-sub-456"


# =============================================================================
# ShifterOIDCBackend._update_cognito_sub
# =============================================================================


@pytest.mark.django_db
class TestShifterOIDCBackendUpdateCognitoSub:
    """``_update_cognito_sub`` against the real management service + UserProfile."""

    def _user(self):
        return User.objects.create_user(username="cogsub@example.com", email="cogsub@example.com")

    def test_persists_cognito_sub_from_claims(self):
        """The sub from claims is stored on the user's profile."""
        backend = ShifterOIDCBackend()
        user = self._user()

        backend._update_cognito_sub(user, {"sub": "abc-123-cognito-sub", "email": user.email})

        assert get_user_profile(user).cognito_sub == "abc-123-cognito-sub"

    @pytest.mark.parametrize("claims", [{}, {"sub": None}, {"sub": ""}], ids=["missing", "none", "empty"])
    def test_no_op_when_sub_absent(self, claims):
        """A missing/blank sub leaves the profile's cognito_sub unset."""
        backend = ShifterOIDCBackend()
        user = self._user()

        backend._update_cognito_sub(user, claims)

        assert not get_user_profile(user).cognito_sub


# =============================================================================
# ShifterOIDCBackend.authenticate audit coverage (OIDC callback events)
# =============================================================================


def _audit_request():
    """A minimal request with the fields the audit path reads."""
    request = MagicMock()
    request.META = {"REMOTE_ADDR": "10.0.0.5", "HTTP_USER_AGENT": "Browser/1.0"}
    return request


@pytest.mark.django_db
class TestShifterOIDCBackendAuthenticateAudit:
    """``authenticate`` writes durable audit rows for OIDC callback outcomes.

    Drives the real ``authenticate`` wrapper and the real ``audit_auth_event``,
    stubbing only the mozilla base ``authenticate`` (the provider/token exchange
    boundary) to force success, ``None``, and raising outcomes.
    """

    def test_successful_auth_writes_login_row(self):
        user = User.objects.create_user(username="oidc-ok@example.com", email="oidc-ok@example.com")
        backend = ShifterOIDCBackend()

        with patch.object(OIDCAuthenticationBackend, "authenticate", return_value=user):
            result = backend.authenticate(_audit_request())

        assert result == user
        row = AuditLog.objects.get(action=AuditLog.Action.LOGIN, entity_type=AuditLog.EntityType.USER)
        assert row.new_state["email"] == "oidc-ok@example.com"
        assert row.source_ip == "10.0.0.5"

    def test_none_result_writes_login_failed_row(self):
        backend = ShifterOIDCBackend()

        with patch.object(OIDCAuthenticationBackend, "authenticate", return_value=None):
            result = backend.authenticate(_audit_request())

        assert result is None
        row = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
        assert row.source_ip == "10.0.0.5"

    def test_exception_writes_login_failed_with_bounded_reason_and_reraises(self):
        """Token/validation errors raised before the ``None`` branch are audited.

        The reason must be the bounded exception *type*, never ``str(exc)``,
        which can carry token endpoint URLs, response bodies, codes, or client
        ids. The original exception must propagate so mozilla's callback failure
        handling is unchanged.
        """
        backend = ShifterOIDCBackend()
        leaky = SuspiciousOperation("JWT signature invalid token=eyJraWQ-secret code=abc123")

        with (
            patch.object(OIDCAuthenticationBackend, "authenticate", side_effect=leaky),
            pytest.raises(SuspiciousOperation),
        ):
            backend.authenticate(_audit_request())

        row = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
        assert "SuspiciousOperation" in row.context
        assert "secret" not in row.context
        assert "abc123" not in row.context
