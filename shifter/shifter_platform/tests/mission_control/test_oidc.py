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
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
)
from shared.auth import CTF_ORGANIZER_GROUP

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


TEST_ISSUER = "https://issuer.example.test"


def _stashed_backend(issuer=TEST_ISSUER, subject="sub-1"):
    """A ShifterOIDCBackend with (issuer, subject) pre-stashed, as verify_token
    would have set them from a real callback (issue #1521)."""
    backend = ShifterOIDCBackend()
    backend._verified_issuer = issuer
    backend._verified_subject = subject
    return backend


@pytest.mark.django_db
class TestShifterOIDCBackendBootstrapAdmin:
    """OIDC bootstrap staff/superuser elevation, driven through the real backend.

    Drives the real ``create_user`` / ``update_user`` (the mozilla base really
    creates/updates the Django user from claims), the real
    ``apply_bootstrap_admin_flags``, the real ``bind_provider_identity``
    management service, and the real ``audit_auth_event`` — asserting
    persisted state (flags, profile, audit row) instead of patching them.
    ``_verified_issuer`` / ``_verified_subject`` are pre-stashed on the
    backend the way ``verify_token`` would set them from a real callback
    (issue #1521); ``verify_token`` itself is covered separately in
    ``TestShifterOIDCBackendVerifyToken``.
    """

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["admin@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["admin@example.com"],
    )
    def test_create_user_applies_bootstrap_admin_flags(self):
        """OIDC first login elevates configured bootstrap admin emails."""
        backend = _stashed_backend(subject="cognito-sub-123")
        claims = {"email": "admin@example.com", "sub": "cognito-sub-123", "email_verified": True}

        created_user = backend.create_user(claims)

        created_user.refresh_from_db()
        assert created_user.email == "admin@example.com"
        assert created_user.is_staff is True
        assert created_user.is_superuser is True
        # (issuer, subject) bound via the real management service.
        profile = get_user_profile(created_user)
        assert profile.cognito_sub == "cognito-sub-123"
        assert profile.issuer == TEST_ISSUER
        # New-user audit row written via the real audit service.
        assert AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, action=AuditAction.CREATE, actor_type=AuditActorType.COGNITO
        ).exists()
        # Strict bind/elevate security-mutation audit row (issue #1521).
        assert AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, action=AuditAction.ROLE_SYNC, entity_id=created_user.id
        ).exists()

    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["ops@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[],
    )
    def test_update_user_applies_bootstrap_staff_flags(self):
        """Returning OIDC users are elevated when bootstrap settings change."""
        backend = _stashed_backend(subject="cognito-sub-456")
        user = User.objects.create_user(username="ops@example.com", email="ops@example.com")
        claims = {"email": "ops@example.com", "sub": "cognito-sub-456", "email_verified": True}

        updated_user = backend.update_user(user, claims)

        updated_user.refresh_from_db()
        assert updated_user.is_staff is True
        assert updated_user.is_superuser is False
        profile = get_user_profile(updated_user)
        assert profile.cognito_sub == "cognito-sub-456"
        assert profile.issuer == TEST_ISSUER

    def test_create_user_rejects_missing_email_verified(self):
        """No write survives when email_verified is absent (issue #1521)."""
        backend = _stashed_backend(subject="cognito-sub-noverify")
        claims = {"email": "noverify@example.com", "sub": "cognito-sub-noverify"}

        with pytest.raises(SuspiciousOperation):
            backend.create_user(claims)

        assert not User.objects.filter(email="noverify@example.com").exists()

    @pytest.mark.parametrize(
        "email_verified",
        [False, "false", 0, 1],
        ids=["false", "str-false", "int-0", "int-1"],
    )
    def test_create_user_rejects_non_literal_true_email_verified(self, email_verified):
        backend = _stashed_backend(subject="cognito-sub-malformed")
        claims = {"email": "malformed@example.com", "sub": "cognito-sub-malformed", "email_verified": email_verified}

        with pytest.raises(SuspiciousOperation):
            backend.create_user(claims)

        assert not User.objects.filter(email="malformed@example.com").exists()

    def test_create_user_accepts_cognito_string_true_email_verified(self):
        """Cognito UserInfo returns email_verified as the string 'true'; the
        create/bind path must accept it (issue: proof login rejected)."""
        backend = _stashed_backend(subject="cognito-sub-strtrue")
        claims = {"email": "strtrue@example.com", "sub": "cognito-sub-strtrue", "email_verified": "true"}

        created = backend.create_user(claims)

        created.refresh_from_db()
        assert created.email == "strtrue@example.com"
        assert User.objects.filter(email="strtrue@example.com").exists()


@pytest.mark.django_db
class TestShifterOIDCBackendOrganizerAuthority:
    """#1516 end-to-end through the real OIDC backend.

    Self-service ``custom:user_type`` can never grant ``CTF Organizer``; only an
    allowlisted, administrator-controlled provider group (``cognito:groups``)
    does. Drives the real ``create_user`` pipeline (bootstrap flags, user-type
    sync, cognito-group capture, and the provider-authority reconcile).
    """

    _ORG_PROVIDER_GROUP = "shifter-ctf-organizers"

    def _organizer_groups(self, user):
        return set(user.groups.values_list("name", flat=True))

    def test_self_service_user_type_organizer_claim_grants_no_organizer(self):
        backend = _stashed_backend(subject="sub-attacker")
        # A participant self-asserts the organizer user_type; no provider group,
        # allowlist unset -> the self-service path must not reach organizer.
        claims = {
            "email": "attacker@example.com",
            "sub": "sub-attacker",
            "email_verified": True,
            "custom:user_type": "ctf_organizer",
        }
        user = backend.create_user(claims)
        user.refresh_from_db()
        assert CTF_ORGANIZER_GROUP not in self._organizer_groups(user)
        assert user.is_staff is False
        assert user.is_superuser is False

    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[_ORG_PROVIDER_GROUP])
    def test_allowlisted_provider_group_grants_organizer(self):
        backend = _stashed_backend(subject="sub-lead")
        claims = {
            "email": "lead@example.com",
            "sub": "sub-lead",
            "email_verified": True,
            "cognito:groups": [self._ORG_PROVIDER_GROUP],
        }
        user = backend.create_user(claims)
        assert CTF_ORGANIZER_GROUP in self._organizer_groups(user)

    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[_ORG_PROVIDER_GROUP])
    def test_self_service_claim_with_non_allowlisted_provider_group_grants_no_organizer(self):
        backend = _stashed_backend(subject="sub-attacker2")
        # Combining a self-asserted organizer user_type with a non-allowlisted
        # provider group still grants nothing — neither path admits organizer.
        claims = {
            "email": "attacker2@example.com",
            "sub": "sub-attacker2",
            "email_verified": True,
            "custom:user_type": "ctf_organizer",
            "cognito:groups": ["random-group"],
        }
        user = backend.create_user(claims)
        assert CTF_ORGANIZER_GROUP not in self._organizer_groups(user)

    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[_ORG_PROVIDER_GROUP])
    def test_provider_group_removal_revokes_previously_granted_organizer(self):
        # Authoritative provider source: once the administrator removes the user
        # from the allowlisted provider group, the next verified login revokes the
        # provider-derived organizer membership (codex review #1516).
        email, sub = "wasorg@example.com", "sub-wasorg"
        backend = _stashed_backend(subject=sub)
        user = backend.create_user(
            {"email": email, "sub": sub, "email_verified": True, "cognito:groups": [self._ORG_PROVIDER_GROUP]}
        )
        assert CTF_ORGANIZER_GROUP in self._organizer_groups(user)

        backend.update_user(user, {"email": email, "sub": sub, "email_verified": True, "cognito:groups": []})
        user.refresh_from_db()
        assert CTF_ORGANIZER_GROUP not in self._organizer_groups(user)


# =============================================================================
# ShifterOIDCBackend.verify_token (issue #1521)
# =============================================================================


class TestShifterOIDCBackendVerifyToken:
    """Issuer/audience/authorized-party checks layered on mozilla's base verify_token.

    mozilla-django-oidc 5.0.2's base ``verify_token`` decodes with
    ``verify_aud=False`` and is not given an expected issuer, so the persisted
    issuer/subject cannot be trusted from the base call alone (issue #1521).
    Patches only the mozilla provider boundary (the JWS/JWT decode itself, via
    ``OIDCAuthenticationBackend.verify_token``) so these tests exercise our own
    override's assertions against a controlled decoded payload.
    """

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_accepts_matching_issuer_and_audience_and_stashes_evidence(self):
        backend = ShifterOIDCBackend()
        payload = {"iss": TEST_ISSUER, "aud": "client-abc", "sub": "sub-1"}

        with patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload):
            result = backend.verify_token("token")

        assert result == payload
        assert backend._verified_issuer == TEST_ISSUER
        assert backend._verified_subject == "sub-1"

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_accepts_audience_list_containing_client_id(self):
        backend = ShifterOIDCBackend()
        payload = {"iss": TEST_ISSUER, "aud": ["client-abc", "other-aud"], "sub": "sub-1"}

        with patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload):
            result = backend.verify_token("token")

        assert result == payload

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_rejects_issuer_mismatch(self):
        backend = ShifterOIDCBackend()
        payload = {"iss": "https://attacker.example.test", "aud": "client-abc", "sub": "sub-1"}

        with (
            patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload),
            pytest.raises(SuspiciousOperation),
        ):
            backend.verify_token("token")

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_rejects_audience_mismatch(self):
        backend = ShifterOIDCBackend()
        payload = {"iss": TEST_ISSUER, "aud": "someone-elses-client", "sub": "sub-1"}

        with (
            patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload),
            pytest.raises(SuspiciousOperation),
        ):
            backend.verify_token("token")

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_rejects_authorized_party_mismatch(self):
        backend = ShifterOIDCBackend()
        payload = {
            "iss": TEST_ISSUER,
            "aud": ["client-abc", "other-aud"],
            "azp": "someone-elses-client",
            "sub": "sub-1",
        }

        with (
            patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload),
            pytest.raises(SuspiciousOperation),
        ):
            backend.verify_token("token")

    @override_settings(OIDC_ISSUER_URL=TEST_ISSUER, OIDC_RP_CLIENT_ID="client-abc")
    def test_rejects_missing_subject(self):
        backend = ShifterOIDCBackend()
        payload = {"iss": TEST_ISSUER, "aud": "client-abc"}

        with (
            patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload),
            pytest.raises(SuspiciousOperation),
        ):
            backend.verify_token("token")

    @override_settings(OIDC_ISSUER_URL="", OIDC_RP_CLIENT_ID="client-abc")
    def test_rejects_when_no_expected_issuer_configured(self):
        """Fail closed rather than accept any issuer when OIDC_ISSUER_URL is unset."""
        backend = ShifterOIDCBackend()
        payload = {"iss": TEST_ISSUER, "aud": "client-abc", "sub": "sub-1"}

        with (
            patch.object(OIDCAuthenticationBackend, "verify_token", return_value=payload),
            pytest.raises(SuspiciousOperation),
        ):
            backend.verify_token("token")


# =============================================================================
# ShifterOIDCBackend.verify_claims (issue #1521)
# =============================================================================


class TestShifterOIDCBackendVerifyClaims:
    """Literal email_verified=True plus UserInfo/ID-token subject parity."""

    def test_accepts_verified_matching_subject(self):
        backend = _stashed_backend(subject="sub-1")
        claims = {"sub": "sub-1", "email": "u@example.com", "email_verified": True}
        assert backend.verify_claims(claims) is True

    def test_rejects_missing_email_verified(self):
        backend = _stashed_backend(subject="sub-1")
        claims = {"sub": "sub-1", "email": "u@example.com"}
        assert backend.verify_claims(claims) is False

    @pytest.mark.parametrize(
        "value",
        [False, "false", 0, 1],
        ids=["false", "str-false", "int-0", "int-1"],
    )
    def test_rejects_non_literal_true_email_verified(self, value):
        backend = _stashed_backend(subject="sub-1")
        claims = {"sub": "sub-1", "email": "u@example.com", "email_verified": value}
        assert backend.verify_claims(claims) is False

    @pytest.mark.parametrize("value", [True, "true", "True", " TRUE "], ids=["bool", "str", "str-caps", "str-pad"])
    def test_accepts_verified_boolean_or_cognito_string(self, value):
        """Cognito's UserInfo returns email_verified as the string 'true'; the
        ID token returns a boolean. Both must be accepted (the string quirk
        otherwise blocks all Cognito logins)."""
        backend = _stashed_backend(subject="sub-1")
        claims = {"sub": "sub-1", "email": "u@example.com", "email_verified": value}
        assert backend.verify_claims(claims) is True

    def test_rejects_subject_mismatch_with_verified_id_token(self):
        """UserInfo's sub must equal the already-verified ID-token sub."""
        backend = _stashed_backend(subject="sub-from-id-token")
        claims = {"sub": "sub-from-userinfo", "email": "u@example.com", "email_verified": True}
        assert backend.verify_claims(claims) is False

    def test_rejects_when_no_verified_subject_stashed(self):
        backend = ShifterOIDCBackend()
        claims = {"sub": "sub-1", "email": "u@example.com", "email_verified": True}
        assert backend.verify_claims(claims) is False

    def test_rejects_missing_email(self):
        backend = _stashed_backend(subject="sub-1")
        claims = {"sub": "sub-1", "email_verified": True}
        assert backend.verify_claims(claims) is False


# =============================================================================
# ShifterOIDCBackend.filter_users_by_claims (issue #1521)
# =============================================================================


@pytest.mark.django_db
class TestShifterOIDCBackendFilterUsersByClaims:
    """Subject-first account resolution, falling back to email only when no
    stored profile is bound to the (issuer, subject) or a legacy subject-only
    row."""

    def test_resolves_exact_bound_tuple_over_a_different_email(self):
        user = User.objects.create_user(username="bound@example.com", email="bound@example.com")
        profile = get_user_profile(user)
        profile.issuer = TEST_ISSUER
        profile.cognito_sub = "sub-bound"
        profile.save(update_fields=["issuer", "cognito_sub"])
        backend = _stashed_backend(subject="sub-bound")

        result = backend.filter_users_by_claims({"email": "someone-else@example.com"})

        assert list(result) == [user]

    def test_resolves_legacy_subject_only_row_over_a_different_email(self):
        user = User.objects.create_user(username="legacy@example.com", email="legacy@example.com")
        profile = get_user_profile(user)
        profile.cognito_sub = "sub-legacy"
        profile.issuer = ""
        profile.save(update_fields=["cognito_sub", "issuer"])
        backend = _stashed_backend(subject="sub-legacy")

        result = backend.filter_users_by_claims({"email": "someone-else@example.com"})

        assert list(result) == [user]

    def test_falls_back_to_email_lookup_when_no_subject_bound(self):
        user = User.objects.create_user(username="unbound@example.com", email="unbound@example.com")
        backend = _stashed_backend(subject="sub-fresh")

        result = backend.filter_users_by_claims({"email": "unbound@example.com"})

        assert list(result) == [user]

    def test_falls_back_to_base_email_lookup_when_no_verified_subject_stashed(self):
        user = User.objects.create_user(username="nostash@example.com", email="nostash@example.com")
        backend = ShifterOIDCBackend()

        result = backend.filter_users_by_claims({"email": "nostash@example.com"})

        assert list(result) == [user]


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
        row = AuditLog.objects.get(action=AuditAction.LOGIN, entity_type=AuditEntityType.USER)
        assert row.new_state["email"] == "oidc-ok@example.com"
        assert row.source_ip == "10.0.0.5"

    def test_none_result_writes_login_failed_row(self):
        backend = ShifterOIDCBackend()

        with patch.object(OIDCAuthenticationBackend, "authenticate", return_value=None):
            result = backend.authenticate(_audit_request())

        assert result is None
        row = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
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

        request = _audit_request()
        with (
            patch.object(OIDCAuthenticationBackend, "authenticate", side_effect=leaky),
            pytest.raises(SuspiciousOperation),
        ):
            backend.authenticate(request)

        row = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
        assert "SuspiciousOperation" in row.context
        assert "secret" not in row.context
        assert "abc123" not in row.context
