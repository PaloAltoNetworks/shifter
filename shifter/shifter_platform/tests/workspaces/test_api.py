"""DRF boundary tests for workspace membership lifecycle."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db


def _user(django_user_model, suffix: str):
    return django_user_model.objects.create_user(
        username=f"workspace-api-{suffix}@example.com",
        email=f"workspace-api-{suffix}@example.com",
    )


@pytest.fixture
def workspace_owner(django_user_model):
    owner = _user(django_user_model, "owner")
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="API Lab"),
        name="API Workspace",
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    return workspace, owner


def _member(workspace, user, role=WorkspaceRole.MEMBER):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _token_client(user, *granted_scopes: str) -> APIClient:
    _, raw = ApiToken.create_token(name="workspace-api", created_by=user, scopes=list(granted_scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _urls(workspace):
    base = f"/api/v1/workspaces/{workspace.uuid}/"
    return {
        "self": f"{base}membership/",
        "roster": f"{base}memberships/",
        "role": lambda user_id: f"{base}memberships/{user_id}/role/",
        "remove": lambda user_id: f"{base}memberships/{user_id}/remove/",
        "leave": f"{base}memberships/leave/",
    }


def test_anonymous_request_is_denied(workspace_owner):
    workspace, _ = workspace_owner

    response = APIClient().get(_urls(workspace)["self"])

    assert response.status_code == 401


@pytest.mark.parametrize("role", WorkspaceRole.values)
def test_session_member_can_read_own_effective_membership(workspace_owner, django_user_model, role):
    workspace, owner = workspace_owner
    actor = owner if role == WorkspaceRole.OWNER else _user(django_user_model, role)
    if actor != owner:
        _member(workspace, actor, role)

    response = _client(actor).get(_urls(workspace)["self"])

    assert response.status_code == 200
    assert response.json()["user_id"] == actor.pk
    assert response.json()["role"] == role
    assert response.json()["workspace_uuid"] == str(workspace.uuid)


def test_member_cannot_read_roster(workspace_owner, django_user_model):
    workspace, _ = workspace_owner
    member = _user(django_user_model, "member")
    _member(workspace, member)

    response = _client(member).get(_urls(workspace)["roster"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "workspace_access_denied"


def test_owner_adds_changes_and_removes_existing_user_with_strict_audit(workspace_owner, django_user_model):
    workspace, owner = workspace_owner
    target = _user(django_user_model, "target")
    urls = _urls(workspace)
    client = _client(owner)

    added = client.post(
        urls["roster"],
        {"email": target.email, "role": WorkspaceRole.MEMBER},
        format="json",
        HTTP_X_REQUEST_ID="workspace-api-request",
    )
    changed = client.post(
        urls["role"](target.pk),
        {"role": WorkspaceRole.ADMIN},
        format="json",
        HTTP_X_REQUEST_ID="workspace-api-request",
    )
    removed = client.post(
        urls["remove"](target.pk),
        {},
        format="json",
        HTTP_X_REQUEST_ID="workspace-api-request",
    )

    assert added.status_code == 200
    assert added.json()["role"] == WorkspaceRole.MEMBER
    assert changed.status_code == 200
    assert changed.json()["role"] == WorkspaceRole.ADMIN
    assert removed.status_code == 200
    assert removed.json()["user_id"] == target.pk
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
    audits = AuditLog.objects.filter(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        entity_id=added.json()["membership_id"],
    ).order_by("timestamp")
    assert list(audits.values_list("action", flat=True)) == [
        AuditAction.CREATE,
        AuditAction.UPDATE,
        AuditAction.DELETE,
    ]
    assert all(row.request_id == "workspace-api-request" for row in audits)


def test_member_can_leave(workspace_owner, django_user_model):
    workspace, _ = workspace_owner
    member = _user(django_user_model, "member")
    _member(workspace, member)

    response = _client(member).post(_urls(workspace)["leave"], {}, format="json")

    assert response.status_code == 200
    assert response.json()["user_id"] == member.pk
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=member).exists()


def test_write_validation_uses_closed_role(workspace_owner, django_user_model):
    workspace, owner = workspace_owner
    target = _user(django_user_model, "target")

    response = _client(owner).post(
        _urls(workspace)["roster"],
        {"email": target.email, "role": "superuser"},
        format="json",
    )

    assert response.status_code == 400
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()


def test_missing_membership_maps_to_not_found(workspace_owner, django_user_model):
    workspace, owner = workspace_owner
    nonmember = _user(django_user_model, "missing")

    response = _client(owner).post(
        _urls(workspace)["role"](nonmember.pk),
        {"role": WorkspaceRole.MEMBER},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "membership_not_found"


def test_conflicting_duplicate_membership_maps_to_conflict(workspace_owner, django_user_model):
    workspace, owner = workspace_owner
    target = _user(django_user_model, "duplicate")
    _member(workspace, target, WorkspaceRole.MEMBER)

    response = _client(owner).post(
        _urls(workspace)["roster"],
        {"email": target.email, "role": WorkspaceRole.ADMIN},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "membership_exists"


def test_last_owner_leave_maps_to_conflict(workspace_owner):
    workspace, owner = workspace_owner

    response = _client(owner).post(_urls(workspace)["leave"], {}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner_required"


def test_personal_workspace_mutation_maps_to_conflict(django_user_model):
    from workspaces import services
    from workspaces.models import Workspace

    owner = _user(django_user_model, "personal")
    personal = services.resolve_personal_workspace(owner)
    workspace = Workspace.objects.get(pk=personal.workspace_id)

    response = _client(owner).post(_urls(workspace)["leave"], {}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "personal_workspace_protected"


def test_remove_self_maps_to_use_leave_conflict(workspace_owner):
    workspace, owner = workspace_owner

    response = _client(owner).post(_urls(workspace)["remove"](owner.pk), {}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "use_leave_operation"


def test_admin_owner_grant_maps_to_forbidden(workspace_owner, django_user_model):
    workspace, _owner = workspace_owner
    admin = _user(django_user_model, "admin-owner-grant")
    target = _user(django_user_model, "owner-target")
    _member(workspace, admin, WorkspaceRole.ADMIN)
    _member(workspace, target, WorkspaceRole.MEMBER)

    response = _client(admin).post(
        _urls(workspace)["role"](target.pk),
        {"role": WorkspaceRole.OWNER},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "owner_authority_required"


def test_unknown_account_add_maps_to_not_found(workspace_owner):
    workspace, owner = workspace_owner

    response = _client(owner).post(
        _urls(workspace)["roster"],
        {"email": "missing-account@example.com", "role": WorkspaceRole.MEMBER},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "member_add_failed"


def test_read_token_scope_and_role_are_both_required(workspace_owner):
    workspace, owner = workspace_owner
    urls = _urls(workspace)

    admitted = _token_client(owner, scopes.WORKSPACES_MEMBERSHIP_READ).get(urls["roster"])
    wrong_scope = _token_client(owner, scopes.MISSION_CONTROL_RANGE_READ).get(urls["roster"])

    assert admitted.status_code == 200
    assert wrong_scope.status_code == 403


def test_write_token_requires_write_scope(workspace_owner, django_user_model):
    workspace, owner = workspace_owner
    target = _user(django_user_model, "target")
    payload = {"email": target.email, "role": WorkspaceRole.MEMBER}

    read_only = _token_client(owner, scopes.WORKSPACES_MEMBERSHIP_READ).post(
        _urls(workspace)["roster"],
        payload,
        format="json",
    )
    writer = _token_client(owner, scopes.WORKSPACES_MEMBERSHIP_WRITE).post(
        _urls(workspace)["roster"],
        payload,
        format="json",
    )

    assert read_only.status_code == 403
    assert writer.status_code == 200
    audit = AuditLog.objects.get(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        action=AuditAction.CREATE,
        entity_id=writer.json()["membership_id"],
    )
    assert audit.actor_type == AuditActorType.APIKEY


def test_write_token_role_is_enforced_after_scope(workspace_owner, django_user_model):
    workspace, _ = workspace_owner
    member = _user(django_user_model, "member")
    target = _user(django_user_model, "target")
    _member(workspace, member)

    response = _token_client(member, scopes.WORKSPACES_MEMBERSHIP_WRITE).post(
        _urls(workspace)["roster"],
        {"email": target.email, "role": WorkspaceRole.MEMBER},
        format="json",
    )

    assert response.status_code == 403
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()


def test_unknown_workspace_and_non_member_share_the_same_denial(django_user_model):
    actor = _user(django_user_model, "actor")
    other = _user(django_user_model, "other")
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Other"),
        name="Other",
    )
    _member(workspace, other, WorkspaceRole.OWNER)
    unknown = "00000000-0000-4000-8000-000000000000"

    existing_response = _client(actor).get(_urls(workspace)["self"])
    unknown_response = _client(actor).get(f"/api/v1/workspaces/{unknown}/membership/")

    assert existing_response.status_code == unknown_response.status_code == 403
    assert existing_response.json()["error"]["code"] == unknown_response.json()["error"]["code"]
