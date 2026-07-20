"""Integration tests for the Administer user-administration API (#1373).

Drives the real DRF endpoints against real ``User`` / ``UserProfile`` /
``AuditLog`` rows: authorization (staff + per-operation model permission, token
principals rejected), bounded list filters + pagination, the read-serializer
secret scrub (no identity-binding fields), the account-status lifecycle
operations, and their strict, request-attributed audit rows.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient

from management.models import UserProfile
from risk_register.models import AuditLog
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditEntityType

pytestmark = pytest.mark.django_db

User = get_user_model()

USERS_URL = "/api/v1/administer/users/"


def _perm(codename: str) -> Permission:
    return Permission.objects.get(content_type__app_label="auth", codename=codename)


def _make_user(username: str, **kwargs) -> User:
    return User.objects.create_user(username=username, email=f"{username}@example.com", **kwargs)


@pytest.fixture
def admin() -> User:
    """Superuser: implicitly holds every model permission."""
    return User.objects.create_superuser(username="root", email="root@example.com", password="pw")


@pytest.fixture
def viewer() -> User:
    """Staff user with only ``auth.view_user`` (read, but no mutations)."""
    user = _make_user("viewer", is_staff=True)
    user.user_permissions.add(_perm("view_user"))
    return user


@pytest.fixture
def target() -> User:
    return _make_user("target")


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestAuthorization:
    def test_anonymous_denied(self):
        assert APIClient().get(USERS_URL).status_code in (401, 403)

    def test_non_staff_denied(self, target):
        assert _client(target).get(USERS_URL).status_code == 403

    def test_staff_without_view_perm_denied(self):
        staff = _make_user("bare_staff", is_staff=True)
        assert _client(staff).get(USERS_URL).status_code == 403

    def test_viewer_can_list_but_not_mutate(self, viewer, target):
        client = _client(viewer)
        assert client.get(USERS_URL).status_code == 200
        # view_user does not grant change_user.
        resp = client.post(f"{USERS_URL}{target.id}/set-active/", {"is_active": False}, format="json")
        assert resp.status_code == 403


class TestUserList:
    def test_list_shape_and_pagination_envelope(self, admin, target):
        body = _client(admin).get(USERS_URL).json()
        assert set(body) == {"count", "next", "previous", "results"}
        assert body["count"] >= 2
        ids = {row["id"] for row in body["results"]}
        assert {admin.id, target.id} <= ids

    def test_read_serializer_scrubs_identity_binding_fields(self, admin, target):
        profile = target.profile
        profile.cognito_sub = "provider-subject-abc"
        profile.issuer = "https://issuer.example"
        profile.cognito_groups = ["provider-group"]
        profile.save(update_fields=["cognito_sub", "issuer", "cognito_groups"])

        row = next(r for r in _client(admin).get(USERS_URL).json()["results"] if r["id"] == target.id)
        for forbidden in ("cognito_sub", "issuer", "cognito_groups"):
            assert forbidden not in row
        assert row["account_origin"] == "provider"

    def test_search_filters_by_username(self, admin):
        _make_user("needle_user")
        _make_user("other_user")
        results = _client(admin).get(USERS_URL, {"search": "needle"}).json()["results"]
        assert results and all("needle" in r["username"] for r in results)

    def test_overlong_search_is_rejected(self, admin):
        assert _client(admin).get(USERS_URL, {"search": "x" * 101}).status_code == 400

    def test_is_active_filter(self, admin):
        disabled = _make_user("disabled_user", is_active=False)
        results = _client(admin).get(USERS_URL, {"is_active": "false"}).json()["results"]
        ids = {r["id"] for r in results}
        assert disabled.id in ids
        assert all(r["is_active"] is False for r in results)

    def test_soft_deleted_excluded_by_default_and_shown_on_opt_in(self, admin, target):
        target.profile.deleted_at = timezone.now()
        target.profile.save(update_fields=["deleted_at"])

        default_ids = {r["id"] for r in _client(admin).get(USERS_URL).json()["results"]}
        assert target.id not in default_ids

        with_deleted = _client(admin).get(USERS_URL, {"include_deleted": "true"}).json()["results"]
        assert target.id in {r["id"] for r in with_deleted}

    def test_invalid_account_origin_is_rejected(self, admin):
        assert _client(admin).get(USERS_URL, {"account_origin": "bogus"}).status_code == 400

    def test_local_filter_includes_profile_less_accounts(self, admin):
        # A profile-less account is classified "local"; the Local filter must not
        # hide it (the reverse-relation join would otherwise drop it).
        orphan = _make_user("orphan")
        UserProfile.objects.filter(user=orphan).delete()

        results = _client(admin).get(USERS_URL, {"account_origin": "local"}).json()["results"]
        row = next((r for r in results if r["id"] == orphan.id), None)
        assert row is not None
        assert row["account_origin"] == "local"


class TestAuthenticationChain:
    """The Administer views keep the canonical bearer-first, fail-closed chain."""

    def test_valid_token_principal_is_rejected(self, admin):
        _token, raw = ApiToken.create_token(name="ci", created_by=admin, scopes=[scopes.RISK_READ])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        # A valid platform token authenticates, then IsStaffSession rejects it:
        # management endpoints are session-only.
        assert client.get(USERS_URL).status_code == 403

    def test_invalid_bearer_fails_closed_even_with_active_session(self, admin):
        # Real session (not force_authenticate, which bypasses the auth classes).
        session_client = APIClient()
        assert session_client.login(username="root", password="pw")
        # Sanity: the session alone is admitted.
        assert session_client.get(USERS_URL).status_code == 200

        # A bad bearer must raise (401) and never fall through to that session.
        session_client.credentials(HTTP_AUTHORIZATION="Bearer shf_bogus.deadbeef")
        assert session_client.get(USERS_URL).status_code == 401


class TestUserDetail:
    def test_detail_includes_groups_and_provenance(self, admin, target):
        body = _client(admin).get(f"{USERS_URL}{target.id}/").json()
        assert body["id"] == target.id
        assert "groups" in body
        assert "organizer_grant_source" in body
        assert "cognito_sub" not in body

    def test_missing_user_is_404(self, admin):
        assert _client(admin).get(f"{USERS_URL}999999/").status_code == 404


class TestSetActive:
    def test_deactivate_writes_audit_and_toggles(self, admin, target):
        resp = _client(admin).post(f"{USERS_URL}{target.id}/set-active/", {"is_active": False}, format="json")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        target.refresh_from_db()
        assert target.is_active is False

        row = AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, entity_id=target.id, action=AuditAction.UPDATE
        ).latest("timestamp")
        assert row.actor_id == admin.id

    def test_self_deactivation_forbidden(self, admin):
        resp = _client(admin).post(f"{USERS_URL}{admin.id}/set-active/", {"is_active": False}, format="json")
        assert resp.status_code == 400
        admin.refresh_from_db()
        assert admin.is_active is True

    def test_missing_body_field_is_400(self, admin, target):
        assert _client(admin).post(f"{USERS_URL}{target.id}/set-active/", {}, format="json").status_code == 400


class TestSoftDelete:
    def test_soft_delete_marks_profile_and_audits(self, admin, target):
        resp = _client(admin).post(f"{USERS_URL}{target.id}/delete/", format="json")
        assert resp.status_code == 200
        assert resp.json()["is_deleted"] is True

        profile = UserProfile.objects.get(user=target)
        assert profile.deleted_at is not None
        assert User.objects.filter(pk=target.id).exists()  # soft delete, not a row delete

        row = AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, entity_id=target.id, action=AuditAction.DELETE
        ).latest("timestamp")
        assert row.actor_id == admin.id

    def test_self_delete_forbidden(self, admin):
        resp = _client(admin).post(f"{USERS_URL}{admin.id}/delete/", format="json")
        assert resp.status_code == 400

    def test_delete_requires_delete_perm(self, viewer, target):
        # viewer has view_user but not delete_user.
        assert _client(viewer).post(f"{USERS_URL}{target.id}/delete/", format="json").status_code == 403
