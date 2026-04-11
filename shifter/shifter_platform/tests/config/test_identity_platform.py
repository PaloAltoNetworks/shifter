"""Tests for the GCP Identity Platform auth path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from config.views import logout_view

User = get_user_model()


@pytest.fixture
def client(db):
    """Django test client with database access."""
    return Client()


@pytest.fixture
def rf():
    """Django request factory."""
    return RequestFactory()


@pytest.fixture
def identity_user(db):
    """Create a standard test user."""
    return User.objects.create_user(
        username="analyst@paloaltonetworks.com",
        email="analyst@paloaltonetworks.com",
    )


@override_settings(AUTH_PROVIDER="oidc", DEBUG=False)
def test_platform_login_redirects_to_oidc(client):
    """AWS/OIDC deployments keep the existing redirect behavior."""
    response = client.get(reverse("platform_login"))

    assert response.status_code == 302
    assert response.url == reverse("oidc_authentication_init")


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_platform_login_renders_identity_platform_form(client):
    """GCP deployments render the first-party login form instead of OIDC redirect."""
    response = client.get(reverse("platform_login"))

    assert response.status_code == 200
    assert b"Sign in to Shifter" in response.content
    assert b'name="email"' in response.content
    assert b'name="password"' in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_password_login_starts_totp_enrollment_for_first_login(client, monkeypatch):
    """Users without an enrolled second factor are forced into TOTP setup."""
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "sign_in_with_password",
        lambda email, password: {
            "idToken": "id-token",
            "refreshToken": "refresh-token",
            "expiresIn": "3600",
            "email": email,
            "localId": "user-123",
            "registered": True,
            "mfaInfo": [],
        },
    )
    monkeypatch.setattr(
        views.identity_platform_auth,
        "start_totp_enrollment",
        lambda id_token, email: {
            "shared_secret_key": "JBSWY3DPEHPK3PXP",
            "session_info": "session-123",
            "verification_code_length": 6,
            "hashing_algorithm": "SHA1",
            "period_sec": 30,
            "otpauth_uri": "otpauth://totp/Shifter:analyst@paloaltonetworks.com?secret=JBSWY3DPEHPK3PXP&issuer=Shifter",
        },
    )

    response = client.post(
        reverse("platform_login"),
        {"action": "password_sign_in", "email": "analyst@paloaltonetworks.com", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert b"Set up multi-factor authentication" in response.content
    assert client.session["identity_platform_enrollment"]["session_info"] == "session-123"
    assert client.session["identity_platform_enrollment"]["email"] == "analyst@paloaltonetworks.com"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_password_login_rejects_non_corporate_email(client, monkeypatch):
    """Non-corporate users are denied even if Identity Platform returns a valid token."""
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "sign_in_with_password",
        lambda email, password: {
            "idToken": "id-token",
            "refreshToken": "refresh-token",
            "expiresIn": "3600",
            "email": email,
            "localId": "user-123",
            "registered": True,
            "mfaInfo": [],
        },
    )

    response = client.post(
        reverse("platform_login"),
        {"action": "password_sign_in", "email": "intruder@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 403
    assert b"@paloaltonetworks.com" in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_password_login_handles_second_factor_challenge(client, monkeypatch):
    """Enrolled users are prompted for the TOTP code instead of receiving a session immediately."""
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "sign_in_with_password",
        lambda email, password: {
            "mfaPendingCredential": "pending-credential",
            "mfaInfo": [{"mfaEnrollmentId": "enrollment-1", "displayName": "Authenticator"}],
        },
    )

    response = client.post(
        reverse("platform_login"),
        {"action": "password_sign_in", "email": "analyst@paloaltonetworks.com", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert b"Enter your authentication code" in response.content
    assert client.session["identity_platform_signin"]["pending_credential"] == "pending-credential"
    assert client.session["identity_platform_signin"]["enrollment_id"] == "enrollment-1"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_totp_enrollment_finalizes_and_creates_django_session(client, monkeypatch, identity_user):
    """Completing MFA enrollment logs the user in through the identity backend."""
    from config import views

    session = client.session
    session["identity_platform_enrollment"] = {
        "email": identity_user.email,
        "id_token": "bootstrap-id-token",
        "session_info": "session-123",
    }
    session.save()

    monkeypatch.setattr(
        views.identity_platform_auth,
        "finalize_totp_enrollment",
        lambda **kwargs: {
            "idToken": "verified-id-token",
            "refreshToken": "refresh-token",
        },
    )
    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: identity_user,
    )

    response = client.post(
        reverse("platform_login"),
        {"action": "complete_totp_enrollment", "verification_code": "123456"},
        follow=False,
    )

    assert response.status_code == 302
    assert response.url == reverse("dashboard_router")
    assert "_auth_user_id" in client.session
    assert BACKEND_SESSION_KEY in client.session
    assert "identity_platform_enrollment" not in client.session


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_totp_signin_finalizes_and_creates_django_session(client, monkeypatch, identity_user):
    """Completing an MFA sign-in challenge logs the user in."""
    from config import views

    session = client.session
    session["identity_platform_signin"] = {
        "pending_credential": "pending-credential",
        "enrollment_id": "enrollment-1",
    }
    session.save()

    monkeypatch.setattr(
        views.identity_platform_auth,
        "finalize_totp_sign_in",
        lambda **kwargs: {
            "idToken": "verified-id-token",
            "refreshToken": "refresh-token",
        },
    )
    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: identity_user,
    )

    response = client.post(
        reverse("platform_login"),
        {"action": "complete_totp_sign_in", "verification_code": "123456"},
        follow=False,
    )

    assert response.status_code == 302
    assert response.url == reverse("dashboard_router")
    assert "_auth_user_id" in client.session
    assert "identity_platform_signin" not in client.session


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_logout_is_plain_session_logout(rf, identity_user):
    """The GCP identity path does not redirect to an external logout endpoint."""
    request = rf.post("/logout/")
    request.user = identity_user
    request.session = {
        BACKEND_SESSION_KEY: "config.identity_platform.IdentityPlatformBackend",
    }

    with pytest.MonkeyPatch.context() as monkeypatch:
        mock_logout = MagicMock()
        monkeypatch.setattr("config.views.logout", mock_logout)
        response = logout_view(request)

    mock_logout.assert_called_once_with(request)
    assert response.status_code == 302
    assert response.url == "/"


def test_identity_backend_enforces_corporate_domain(db, monkeypatch):
    """Verified non-corporate tokens are rejected by the backend seam."""
    from config import identity_platform as identity_platform_auth

    backend = identity_platform_auth.IdentityPlatformBackend()
    request = SimpleNamespace(META={}, session={})

    with pytest.raises(identity_platform_auth.IdentityPlatformAuthError):
        backend.authenticate(
            request,
            identity_claims={
                "sub": "sub-123",
                "email": "intruder@example.com",
                "email_verified": True,
            },
        )


@override_settings(
    PLATFORM_BOOTSTRAP_STAFF_EMAILS=["bedwards@paloaltonetworks.com"],
    PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["bedwards@paloaltonetworks.com"],
)
def test_identity_backend_bootstrap_admin_gets_staff_superuser(db):
    """The bootstrap operator can be elevated from runtime config without repo-hardcoding."""
    from config import identity_platform as identity_platform_auth

    backend = identity_platform_auth.IdentityPlatformBackend()
    request = SimpleNamespace(META={}, session={})

    user = backend.authenticate(
        request,
        identity_claims={
            "sub": "sub-456",
            "email": "bedwards@paloaltonetworks.com",
            "email_verified": True,
        },
    )

    assert user is not None
    user.refresh_from_db()
    assert user.is_staff is True
    assert user.is_superuser is True


def test_totp_provisioning_uri_contains_expected_parameters():
    """The otpauth URI matches the returned TOTP metadata."""
    from config import identity_platform as identity_platform_auth

    uri = identity_platform_auth.build_totp_provisioning_uri(
        email="analyst@paloaltonetworks.com",
        shared_secret_key="JBSWY3DPEHPK3PXP",
        hashing_algorithm="SHA1",
        digits=6,
        period_sec=30,
        issuer="Shifter",
    )

    assert uri.startswith("otpauth://totp/Shifter:analyst%40paloaltonetworks.com?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=Shifter" in uri
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert "period=30" in uri
