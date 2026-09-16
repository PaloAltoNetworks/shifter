"""Integration tests for the offboarding ownership-transfer endpoint (#1943).

Drives the composition-root ``/administer/users/<pk>/transfer-ownership/`` view:
authorization, request validation, and the workspace-ownership override outcome.
Range reassignment is covered by the CMS orchestrator and workspaces service
tests; this file asserts the HTTP contract and the workspace transfer path.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _url(pk: int) -> str:
    return f"/api/v1/administer/users/{pk}/transfer-ownership/"


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


class TestValidation:
    def test_requires_change_permission(self, viewer):
        source, replacement = _make_user("s"), _make_user("r")
        resp = _client(viewer).post(
            _url(source.id), {"replacement_user_id": replacement.id, "resource_kinds": ["ranges"]}, format="json"
        )
        assert resp.status_code == 403

    def test_non_superuser_change_user_rejected(self):
        # A staff user with auth.change_user (but not superuser) cannot transfer
        # ownership: the offboarding command is superuser-only (issue #1943 F5).
        staff = _make_user("staffchange", is_staff=True)
        staff.user_permissions.add(_perm("change_user"))
        source, replacement = _make_user("s"), _make_user("r")
        resp = _client(staff).post(
            _url(source.id), {"replacement_user_id": replacement.id, "resource_kinds": ["workspaces"]}, format="json"
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "superuser_required"

    def test_same_user_rejected(self, admin):
        source = _make_user("s")
        resp = _client(admin).post(
            _url(source.id), {"replacement_user_id": source.id, "resource_kinds": ["ranges"]}, format="json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "same_user"

    def test_replacement_not_found(self, admin):
        source = _make_user("s")
        resp = _client(admin).post(
            _url(source.id), {"replacement_user_id": 999999, "resource_kinds": ["ranges"]}, format="json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "replacement_not_found"

    def test_inactive_replacement_rejected(self, admin):
        source = _make_user("s")
        replacement = _make_user("r", is_active=False)
        resp = _client(admin).post(
            _url(source.id), {"replacement_user_id": replacement.id, "resource_kinds": ["ranges"]}, format="json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "replacement_inactive"

    def test_empty_resource_kinds_rejected(self, admin):
        source, replacement = _make_user("s"), _make_user("r")
        resp = _client(admin).post(
            _url(source.id), {"replacement_user_id": replacement.id, "resource_kinds": []}, format="json"
        )
        assert resp.status_code == 400

    def test_unknown_resource_kind_rejected(self, admin):
        source, replacement = _make_user("s"), _make_user("r")
        resp = _client(admin).post(
            _url(source.id),
            {"replacement_user_id": replacement.id, "resource_kinds": ["credentials"]},
            format="json",
        )
        assert resp.status_code == 400

    def test_missing_user_is_404(self, admin):
        replacement = _make_user("r")
        resp = _client(admin).post(
            _url(999999), {"replacement_user_id": replacement.id, "resource_kinds": ["ranges"]}, format="json"
        )
        assert resp.status_code == 404


class TestWorkspaceTransfer:
    def test_transfers_owned_workspace_to_member(self, admin):
        source, replacement = _make_user("s"), _make_user("r")
        org = Organization.objects.create(name="Org")
        ws = Workspace.objects.create(organization=org, name="Blue")
        WorkspaceMembership.objects.create(workspace=ws, user=source, role=WorkspaceRole.OWNER.value)
        WorkspaceMembership.objects.create(workspace=ws, user=replacement, role=WorkspaceRole.MEMBER.value)

        resp = _client(admin).post(
            _url(source.id),
            {"replacement_user_id": replacement.id, "resource_kinds": ["workspaces"]},
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspaces_transferred"] == 1
        assert body["source_user_id"] == source.id
        assert body["replacement_user_id"] == replacement.id
        assert WorkspaceMembership.objects.get(workspace=ws, user=replacement).role == WorkspaceRole.OWNER.value

    def test_non_member_workspace_reported_blocked(self, admin):
        source, replacement = _make_user("s"), _make_user("r")
        org = Organization.objects.create(name="Org")
        ws = Workspace.objects.create(organization=org, name="Red")
        WorkspaceMembership.objects.create(workspace=ws, user=source, role=WorkspaceRole.OWNER.value)

        resp = _client(admin).post(
            _url(source.id),
            {"replacement_user_id": replacement.id, "resource_kinds": ["workspaces"]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["workspaces_blocked_no_membership"] == 1
