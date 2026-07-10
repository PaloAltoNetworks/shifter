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
    # Native email + password sign-in form (FirebaseUI's email-first flow is
    # incompatible with email enumeration protection, so it was removed).
    assert b'id="identity-email"' in response.content
    assert b'id="identity-password"' in response.content
    assert b'id="identity-auth-submit"' in response.content
    assert b'id="identity-auth-mode-toggle"' in response.content
    assert b"firebaseui" not in response.content
    assert b"firebase-ui-auth" not in response.content
    # TOTP MFA enrollment is only available through the modular Firebase SDK, so
    # the auth script is loaded as a module and the compat builds are not used.
    assert b'type="module"' in response.content
    assert b"firebase-app-compat" not in response.content
    assert b"firebase-auth-compat" not in response.content


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    SITE_URL="https://portal.example.test",
    IDENTITY_PLATFORM_API_KEY="test-api-key",
    IDENTITY_PLATFORM_PROJECT_ID="test-project",
)
def test_platform_login_embeds_parseable_identity_config(client):
    """The embedded ``json_script`` config must parse to a dict in one pass.

    Regression for the double-encoding defect: the view used to pre-serialize the
    config with ``json.dumps`` and the template re-encodes it via ``json_script``,
    so the browser's single ``JSON.parse`` yielded a *string*, ``config.apiKey``
    was ``undefined``, and Firebase init failed with ``auth/invalid-api-key`` —
    leaving the login page stuck on "Loading authentication...".
    """
    response = client.get(reverse("platform_login"))
    assert response.status_code == 200

    match = re.search(
        r'<script id="identity-platform-config" type="application/json">(.*?)</script>',
        response.content.decode("utf-8"),
        re.DOTALL,
    )
    assert match is not None, "identity-platform-config json_script block not rendered"

    config = json.loads(match.group(1))
    assert isinstance(config, dict), "embedded config must decode to an object, not a string"
    assert config["apiKey"] == "test-api-key"
    assert config["projectId"] == "test-project"
    assert config["authDomain"] == "test-project.firebaseapp.com"


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


@override_settings(
    AUTH_PROVIDER="identity_platform",
    DEBUG=False,
    IDENTITY_ALLOWED_EMAIL_DOMAIN="paloaltonetworks.com",
)
def test_identity_platform_session_does_not_leak_exception_detail(client, monkeypatch):
    """A 403 auth failure surfaces only the fixed error code and a classified
    message, never the raw exception text (CodeQL py/stack-trace-exposure).

    IdentityPlatformAuthError is frequently raised with upstream API detail
    interpolated in (e.g. the Identity Platform response body), so str(exc)
    must not flow to the response.
    """
    from config import views

    leaky_detail = "returned non-JSON response: <html>upstream 500 internal trace at module.func</html>"
    monkeypatch.setattr(
        views.identity_platform_auth,
        "login_with_identity_token",
        lambda request, id_token: (_ for _ in ()).throw(
            views.identity_platform_auth.IdentityPlatformAuthError(leaky_detail)
        ),
    )

    response = client.post(
        reverse("identity_platform_session"),
        data=json.dumps({"idToken": "boom"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "identity_platform_auth_failed"
    assert body["message"] == "Authentication failed"
    for leaked in ("non-JSON", "<html>", "upstream", "internal", "trace", "module.func"):
        assert leaked not in body["message"]


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
    IDENTITY_ALLOWED_EMAIL_DOMAIN="example.com",
    PLATFORM_BOOTSTRAP_STAFF_EMAILS=["admin@example.com"],
    PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["admin@example.com"],
)
def test_identity_backend_bootstrap_admin_gets_staff_superuser(db):
    from config import identity_platform as identity_platform_auth

    backend = identity_platform_auth.IdentityPlatformBackend()
    request = SimpleNamespace(META={}, session={})

    user = backend.authenticate(
        request,
        identity_claims={
            "sub": "sub-456",
            "email": "admin@example.com",
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


def test_verify_identity_token_wraps_firebase_verification_errors(monkeypatch):
    """A firebase verification failure surfaces as IdentityPlatformAuthError, not a raw error."""
    from config import identity_platform as ip

    def _raise(*args, **kwargs):
        raise ValueError("bad token")

    monkeypatch.setattr(ip, "_ensure_firebase_app", lambda: None)
    monkeypatch.setattr(ip.firebase_auth, "verify_id_token", _raise)
    with pytest.raises(ip.IdentityPlatformAuthError):
        ip.verify_identity_token("token")
