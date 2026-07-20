"""Behavior tests for the unified logout view (config/views.py:logout_view).

Drives the real view through the test Client with a real session: the real
Django ``logout`` flushes the session and the view redirects appropriately,
instead of patching ``config.views.logout`` and asserting it was called.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.test import Client, override_settings

from risk_register.models import AuditLog
from shared.audit import (
    AuditAction,
    AuditEntityType,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

LOGOUT_URL = "/logout/"


class _FakeOIDCAuthenticationBackend(ModelBackend):
    """Test auth backend whose dotted path contains ``OIDCAuthenticationBackend``.

    ``logout_view`` selects the OIDC branch by that substring, and Django's
    ``get_user`` only trusts a session backend that is in
    ``AUTHENTICATION_BACKENDS``. Registering this real ``ModelBackend`` subclass
    (via ``override_settings``) lets the OIDC logout path run without pulling in
    mozilla-django-oidc's config-dependent backend ``__init__``.
    """


_FAKE_OIDC_BACKEND = "tests.config.test_logout._FakeOIDCAuthenticationBackend"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="logout@example.com", email="logout@example.com")


class TestLogoutView:
    def test_non_oidc_user_gets_session_logout(self, user):
        """A ModelBackend (non-OIDC) user is logged out and sent to the landing page."""
        client = Client()
        client.force_login(user, backend="config.auth.PlatformModelBackend")
        assert "_auth_user_id" in client.session  # logged in

        response = client.post(LOGOUT_URL)

        assert response.status_code == 302
        assert response.url == "/"
        # Real logout flushed the session.
        assert "_auth_user_id" not in client.session

    def test_oidc_user_redirects_to_landing_without_op_logout(self, user):
        """An OIDC-backend user is logged out; with no Cognito logout method
        configured in test settings, the view falls back to the landing page."""
        client = Client()
        client.force_login(user, backend="config.oidc.ShifterOIDCBackend")

        response = client.post(LOGOUT_URL)

        assert response.status_code == 302
        assert response.url == "/"
        assert "_auth_user_id" not in client.session

    @override_settings(
        AUTHENTICATION_BACKENDS=[_FAKE_OIDC_BACKEND],
        OIDC_OP_LOGOUT_URL_METHOD="config.oidc.provider_logout_url",
    )
    def test_oidc_user_redirects_to_provider_logout_url(self, user, monkeypatch):
        """With OIDC_OP_LOGOUT_URL_METHOD set, an OIDC user is redirected to the
        identity provider's logout endpoint (not the local landing page).

        Exercises logout_view's ``import_string(logout_url_method)(request)``
        path and the real ``config.oidc.provider_logout_url`` builder, so a
        regression there (wrong path, swallowed result) leaves the IdP session
        alive and fails this test.
        """
        monkeypatch.setenv("OIDC_AUTH_DOMAIN", "auth.example.com")
        monkeypatch.setenv("OIDC_RP_CLIENT_ID", "client123")

        client = Client()
        # The session backend string contains "OIDCAuthenticationBackend", so
        # logout_view takes the OIDC branch; it is registered above so Django's
        # get_user trusts the session and the user stays authenticated.
        client.force_login(user, backend=_FAKE_OIDC_BACKEND)

        response = client.post(LOGOUT_URL)

        assert response.status_code == 302
        assert "auth.example.com/logout" in response.url
        assert "client_id=client123" in response.url
        assert "_auth_user_id" not in client.session

    def test_unauthenticated_redirects_to_landing(self):
        """An unauthenticated POST redirects to the landing page."""
        response = Client().post(LOGOUT_URL)

        assert response.status_code == 302
        assert response.url == "/"

    def test_get_not_allowed(self, user):
        """GET is rejected (logout is POST-only)."""
        client = Client()
        client.force_login(user)

        response = client.get(LOGOUT_URL)

        assert response.status_code == 405

    def test_logout_writes_audit_row_with_email(self, user):
        """A successful logout writes a LOGOUT audit row identifying the user.

        The identity is captured before Django ``logout`` flushes the session.
        """
        client = Client()
        client.force_login(user, backend="config.oidc.ShifterOIDCBackend")

        client.post(LOGOUT_URL)

        row = AuditLog.objects.get(action=AuditAction.LOGOUT, entity_type=AuditEntityType.USER)
        assert row.new_state["email"] == user.email

    def test_unauthenticated_logout_writes_no_audit_row(self):
        """An unauthenticated POST has no principal to audit."""
        Client().post(LOGOUT_URL)

        assert not AuditLog.objects.filter(action=AuditAction.LOGOUT).exists()
