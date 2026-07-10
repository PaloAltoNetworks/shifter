"""Behavior tests for the unified logout view (config/views.py:logout_view).

Drives the real view through the test Client with a real session: the real
Django ``logout`` flushes the session and the view redirects appropriately,
instead of patching ``config.views.logout`` and asserting it was called.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from risk_register.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()

LOGOUT_URL = "/logout/"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="logout@example.com", email="logout@example.com")


class TestLogoutView:
    def test_non_oidc_user_gets_session_logout(self, user):
        """A ModelBackend (non-OIDC) user is logged out and sent to the landing page."""
        client = Client()
        client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
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

        row = AuditLog.objects.get(action=AuditLog.Action.LOGOUT, entity_type=AuditLog.EntityType.USER)
        assert row.new_state["email"] == user.email

    def test_unauthenticated_logout_writes_no_audit_row(self):
        """An unauthenticated POST has no principal to audit."""
        Client().post(LOGOUT_URL)

        assert not AuditLog.objects.filter(action=AuditLog.Action.LOGOUT).exists()
