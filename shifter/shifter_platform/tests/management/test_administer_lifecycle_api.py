"""Integration tests for the Administer lifecycle + password-reset API (#1943).

Drives the real DRF endpoints: the closed lifecycle transition command
(``/lifecycle/``), the account-origin-aware password-reset trigger
(``/reset-password/``), and the detail projection's server-derived
``lifecycle_state`` / ``available_actions``. Authorization, guards, and audit are
asserted against real rows.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from shared.audit import AuditAction, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()

USERS_URL = "/api/v1/administer/users/"


def _perm(codename: str) -> Permission:
    return Permission.objects.get(content_type__app_label="auth", codename=codename)


def _make_user(username: str, **kwargs) -> User:
    return User.objects.create_user(username=username, email=f"{username}@example.com", **kwargs)


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin() -> User:
    return User.objects.create_superuser(username="root", email="root@example.com", password="pw")


@pytest.fixture
def viewer() -> User:
    user = _make_user("viewer", is_staff=True)
    user.user_permissions.add(_perm("view_user"))
    return user


@pytest.fixture
def target() -> User:
    return _make_user("target")


class TestLifecycleEndpoint:
    def test_suspend_sets_state_and_returns_projection(self, admin, target):
        resp = _client(admin).post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "suspend"}, format="json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["lifecycle_state"] == "suspended"
        assert body["is_active"] is False
        assert "available_actions" in body
        target.refresh_from_db()
        assert target.profile.suspended_at is not None

    def test_deactivate_then_activate_cycle(self, admin, target):
        client = _client(admin)
        client.post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "deactivate"}, format="json")
        resp = client.post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "activate"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "active"

    def test_invalid_action_is_400(self, admin, target):
        resp = _client(admin).post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "nope"}, format="json")
        assert resp.status_code == 400

    def test_requires_change_permission(self, viewer, target):
        resp = _client(viewer).post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "suspend"}, format="json")
        assert resp.status_code == 403

    def test_self_suspend_forbidden(self, admin):
        resp = _client(admin).post(f"{USERS_URL}{admin.id}/lifecycle/", {"action": "suspend"}, format="json")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "self_action_forbidden"

    def test_suspend_writes_audit(self, admin, target):
        _client(admin).post(f"{USERS_URL}{target.id}/lifecycle/", {"action": "suspend"}, format="json")
        row = AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, entity_id=target.id, action=AuditAction.UPDATE
        ).latest("timestamp")
        assert row.actor_id == admin.id


class TestDetailProjection:
    def test_detail_includes_lifecycle_fields(self, admin, target):
        body = _client(admin).get(f"{USERS_URL}{target.id}/").json()
        assert body["lifecycle_state"] == "active"
        assert isinstance(body["available_actions"], list)
        assert "suspend" in body["available_actions"]


@pytest.fixture
def public_site(settings):
    """A valid public origin + in-memory email so reset delivery works in tests."""
    settings.SITE_URL = "https://portal.example.com"
    settings.DEBUG = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    return settings


class TestResetPasswordEndpoint:
    def test_local_account_reset_accepted(self, admin, public_site):
        local = _make_user("localuser", password="pw")
        resp = _client(admin).post(f"{USERS_URL}{local.id}/reset-password/", format="json")
        assert resp.status_code == 200
        assert AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, entity_id=local.id, action=AuditAction.UPDATE
        ).exists()

    def test_reset_targets_only_the_resolved_user(self, admin, public_site, django_capture_on_commit_callbacks):
        # Two accounts share an email; the reset must reach only the resolved
        # target, not every account with that address (issue #1943 review F2).
        from django.core import mail

        target = _make_user("dup1", password="pw")
        User.objects.create_user(username="dup2", email=target.email, password="pw")
        with django_capture_on_commit_callbacks(execute=True):
            resp = _client(admin).post(f"{USERS_URL}{target.id}/reset-password/", format="json")
        assert resp.status_code == 200
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [target.email]

    def test_provider_account_reset_rejected(self, admin):
        provider = _make_user("provideruser", password="pw")
        provider.profile.cognito_sub = "sub-123"
        provider.profile.save(update_fields=["cognito_sub"])
        resp = _client(admin).post(f"{USERS_URL}{provider.id}/reset-password/", format="json")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "reset_ineligible"

    def test_reset_requires_change_permission(self, viewer):
        local = _make_user("localuser2", password="pw")
        resp = _client(viewer).post(f"{USERS_URL}{local.id}/reset-password/", format="json")
        assert resp.status_code == 403
