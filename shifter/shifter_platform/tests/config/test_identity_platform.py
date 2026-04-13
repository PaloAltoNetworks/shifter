"""Tests for the GCP Identity Platform auth path."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from config.views import logout_view

User = get_user_model()


def _json_script_payload(response_content: bytes, script_id: str):
    pattern = rf'<script id="{re.escape(script_id)}" type="application/json">(.*?)</script>'
    match = re.search(pattern, response_content.decode("utf-8"), re.DOTALL)
    assert match is not None, f"json_script payload {script_id} not found"
    return json.loads(match.group(1))


@pytest.fixture
def client(db):
    return Client()


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def identity_user(db):
    return User.objects.create_user(
        username="analyst@paloaltonetworks.com",
        email="analyst@paloaltonetworks.com",
    )


@override_settings(AUTH_PROVIDER="oidc", DEBUG=False)
def test_platform_login_redirects_to_oidc(client):
    response = client.get(reverse("platform_login"))

    assert response.status_code == 302
    assert response.url == reverse("oidc_authentication_init")


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
)
def test_platform_login_renders_provider_driven_identity_page(client):
    response = client.get(reverse("platform_login"))

    assert response.status_code == 200
    assert b"identity_platform_auth.js" in response.content
    assert b'id="identity-auth-form"' in response.content
    assert b'id="identity-email"' in response.content
    assert b'id="identity-password"' in response.content
    assert b"firebase-ui-auth.js" not in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
)
def test_platform_login_rejects_post_requests(client):
    response = client.post(reverse("platform_login"))

    assert response.status_code == 405


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
)
def test_platform_login_includes_session_exchange_config(client):
    response = client.get(reverse("platform_login"))

    assert response.status_code == 200
    assert reverse("identity_platform_session").encode() in response.content
    assert b"https://portal.example.test/login/" in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_platform_login_json_script_contains_object_config(client):
    response = client.get(reverse("platform_login"))

    payload = _json_script_payload(response.content, "identity-platform-config")

    assert isinstance(payload, dict)
    assert payload["apiKey"] == "test-api-key"
    assert payload["projectId"] == "test-project"
    assert payload["allowedEmailDomain"] == "paloaltonetworks.com"
    assert payload["sessionExchangeUrl"] == reverse("identity_platform_session")


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
    IDENTITY_ALLOWED_EMAILS=["external@example.com", "contractor@partner.test"],
)
def test_platform_login_never_leaks_external_email_allowlist_to_client(client):
    """The IDENTITY_ALLOWED_EMAILS whitelist must stay server-side only.

    It is enforced by the backend (IdentityPlatformBackend.is_allowed_identity_email).
    Embedding it in the client payload would expose the complete list of
    whitelisted external collaborators to any unauthenticated visitor via page
    source.
    """
    response = client.get(reverse("platform_login"))

    payload = _json_script_payload(response.content, "identity-platform-config")

    assert "allowedEmails" not in payload
    assert b"external@example.com" not in response.content
    assert b"contractor@partner.test" not in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_rejects_non_json(client):
    response = client.post(
        reverse("identity_platform_session"),
        data="not-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_creates_django_session(client, monkeypatch, identity_user):
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: identity_user,
    )

    response = client.post(
        reverse("identity_platform_session"),
        data=json.dumps({"idToken": "verified-id-token"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["redirect_url"] == reverse("dashboard_router")
    assert "_auth_user_id" in client.session
    assert BACKEND_SESSION_KEY in client.session


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_audit_logs_rejected_exchange(client, monkeypatch):
    """Rejected exchanges must emit a LOGIN_FAILED audit event (parity with OIDC)."""
    from config import views
    from risk_register.models import AuditLog

    def raise_disallowed(_request, _token):
        raise views.identity_platform_auth.IdentityPlatformAuthError(
            "Only corporate users from @paloaltonetworks.com may log in through the portal"
        )

    monkeypatch.setattr(views.identity_platform_auth, "login_with_identity_token", raise_disallowed)

    response = client.post(
        reverse("identity_platform_session"),
        data=json.dumps({"idToken": "rejected"}),
        content_type="application/json",
        HTTP_USER_AGENT="pytest-client/1.0",
    )

    assert response.status_code == 403
    entries = AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).order_by("-timestamp")
    assert entries.exists()
    latest = entries.first()
    assert "Identity Platform" in latest.context
    assert "identity_platform_auth_failed" in latest.context
    assert latest.user_agent == "pytest-client/1.0"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_audit_logs_invalid_body(client):
    """Non-JSON bodies must audit as a failed login attempt."""
    from risk_register.models import AuditLog

    response = client.post(
        reverse("identity_platform_session"),
        data="not-json",
        content_type="application/json",
        HTTP_USER_AGENT="pytest-client/1.0",
    )

    assert response.status_code == 400
    entries = AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).order_by("-timestamp")
    assert entries.exists()
    assert "non-JSON body" in entries.first().context


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_returns_email_verification_error(client, monkeypatch):
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: (_ for _ in ()).throw(
            views.identity_platform_auth.IdentityPlatformEmailVerificationRequired(
                "Corporate login requires a verified email address."
            )
        ),
    )

    response = client.post(
        reverse("identity_platform_session"),
        data=json.dumps({"idToken": "unverified-id-token"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"] == "email_verification_required"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_returns_mfa_enrollment_error(client, monkeypatch):
    from config import views

    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: (_ for _ in ()).throw(
            views.identity_platform_auth.IdentityPlatformMFAEnrollmentRequired(
                "Corporate login requires an enrolled multi-factor authenticator."
            )
        ),
    )

    response = client.post(
        reverse("identity_platform_session"),
        data=json.dumps({"idToken": "verified-no-mfa"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"] == "mfa_enrollment_required"


@override_settings(AUTH_PROVIDER="identity_platform", DEBUG=False)
def test_gcp_legacy_oidc_authenticate_redirects_to_platform_login(client):
    response = client.get("/oidc/authenticate/")

    assert response.status_code == 302
    assert response.url == reverse("platform_login")


@override_settings(AUTH_PROVIDER="identity_platform", DEBUG=False)
def test_gcp_legacy_oidc_authenticate_rejects_post_requests(client):
    response = client.post("/oidc/authenticate/")

    assert response.status_code == 405


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_backend_enforces_corporate_domain(db):
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


@override_settings(
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_client_config_derives_auth_domain():
    from config import identity_platform as identity_platform_auth

    config = identity_platform_auth.identity_platform_client_config()

    assert config["apiKey"] == "test-api-key"
    assert config["projectId"] == "test-project"
    assert config["authDomain"] == "test-project.firebaseapp.com"


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_login_with_identity_token_requires_verified_email_and_enrolled_factor(monkeypatch):
    from config import identity_platform as identity_platform_auth

    request = SimpleNamespace(META={}, session={})
    monkeypatch.setattr(
        identity_platform_auth,
        "verify_identity_token",
        lambda token: {
            "sub": "sub-123",
            "email": "analyst@paloaltonetworks.com",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        identity_platform_auth,
        "_lookup_identity_account",
        lambda *, id_token: {
            "email": "analyst@paloaltonetworks.com",
            "emailVerified": True,
            "mfaInfo": [],
        },
    )

    with pytest.raises(identity_platform_auth.IdentityPlatformMFAEnrollmentRequired):
        identity_platform_auth.login_with_identity_token(request, "id-token")


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_logout_is_plain_session_logout(rf, identity_user):
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
    assert response.status_code == 200
    assert b"identity_platform_logout.js" in response.content
    payload = _json_script_payload(response.content, "identity-platform-logout-config")
    assert isinstance(payload, dict)
    assert payload["apiKey"] == "test-api-key"
    assert payload["projectId"] == "test-project"
    assert payload["redirectUrl"] == "/"
