"""DRF boundary tests for the workspace lifecycle API (PLAT-233, issue #1940).

Drives the real endpoints through their authority boundary: session-only
admission (tokens and anonymous callers refused), organization-admin authority
for create/list, the workspace role seam for read/mutate, the public UUID only
on the wire, and opaque denials that hide the missing-versus-forbidden
distinction.
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.roles import OrganizationRole, WorkspaceRole

pytestmark = pytest.mark.django_db

_COLLECTION = "/api/v1/workspaces/"


def _detail(workspace_uuid) -> str:
    return f"/api/v1/workspaces/{workspace_uuid}/"


def _user(django_user_model, suffix, *, is_superuser=False):
    return django_user_model.objects.create_user(
        username=f"wl-api-{suffix}@e.com",
        email=f"wl-api-{suffix}@e.com",
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def organization():
    return Organization.objects.create(name="Lab")


@pytest.fixture
def admin(django_user_model, organization):
    actor = _user(django_user_model, "admin")
    OrganizationMembership.objects.create(organization=organization, user=actor, role=OrganizationRole.ADMIN.value)
    return actor


def _make_workspace(admin, organization, name="Team") -> Workspace:
    """Create an ordinary workspace with ``admin`` as its owner."""
    workspace = Workspace.objects.create(organization=organization, name=name)
    WorkspaceMembership.objects.create(workspace=workspace, user=admin, role=WorkspaceRole.OWNER.value)
    return workspace


# ---------------------------------------------------------------------------
# admission
# ---------------------------------------------------------------------------


def test_anonymous_create_is_denied(organization):
    response = APIClient().post(_COLLECTION, {"organization_uuid": str(organization.uuid), "name": "X"}, format="json")

    assert response.status_code == 401


def test_platform_token_is_rejected(organization, admin):
    _, raw = ApiToken.create_token(name="wl", created_by=admin, scopes=[scopes.WORKSPACES_MEMBERSHIP_READ])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.get(f"{_COLLECTION}?organization={organization.uuid}")

    # Session-only: a valid token principal is refused even for an org admin.
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_admin_creates_a_workspace_with_uuid_only_on_the_wire(organization, admin):
    response = _client(admin).post(
        _COLLECTION, {"organization_uuid": str(organization.uuid), "name": "Blue Team"}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Blue Team"
    assert body["organization_uuid"] == str(organization.uuid)
    assert body["is_archived"] is False
    assert "id" not in body
    assert Workspace.objects.filter(uuid=body["uuid"]).exists()


def test_non_admin_create_is_an_opaque_403(organization, django_user_model):
    outsider = _user(django_user_model, "outsider")

    response = _client(outsider).post(
        _COLLECTION, {"organization_uuid": str(organization.uuid), "name": "Blue Team"}, format="json"
    )

    assert response.status_code == 403
    assert not Workspace.objects.filter(name="Blue Team").exists()


def test_create_with_blank_name_is_rejected(organization, admin):
    response = _client(admin).post(
        _COLLECTION, {"organization_uuid": str(organization.uuid), "name": "   "}, format="json"
    )

    assert response.status_code == 400


def test_create_with_duplicate_name_is_conflict(organization, admin):
    _client(admin).post(_COLLECTION, {"organization_uuid": str(organization.uuid), "name": "Dup"}, format="json")

    response = _client(admin).post(
        _COLLECTION, {"organization_uuid": str(organization.uuid), "name": "Dup"}, format="json"
    )

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_requires_an_organization_parameter(admin):
    response = _client(admin).get(_COLLECTION)

    assert response.status_code == 400


def test_admin_lists_active_workspaces_and_can_include_archived(organization, admin):
    active = _make_workspace(admin, organization, "Active")
    archived = _make_workspace(admin, organization, "Archived")
    _client(admin).post(_detail(archived.uuid) + "archive/")

    default = _client(admin).get(f"{_COLLECTION}?organization={organization.uuid}").json()
    with_archived = _client(admin).get(f"{_COLLECTION}?organization={organization.uuid}&include_archived=true").json()

    assert [w["name"] for w in default] == ["Active"]
    assert {w["name"] for w in with_archived} == {"Active", "Archived"}
    assert str(active.uuid) in {w["uuid"] for w in default}


# ---------------------------------------------------------------------------
# detail + rename
# ---------------------------------------------------------------------------


def test_owner_reads_detail_and_non_member_is_denied(organization, admin, django_user_model):
    workspace = _make_workspace(admin, organization)
    outsider = _user(django_user_model, "outsider")

    assert _client(admin).get(_detail(workspace.uuid)).status_code == 200
    assert _client(outsider).get(_detail(workspace.uuid)).status_code == 403


def test_owner_renames_via_patch(organization, admin):
    workspace = _make_workspace(admin, organization, "Old")

    response = _client(admin).patch(_detail(workspace.uuid), {"name": "New"}, format="json")

    assert response.status_code == 200
    assert response.json()["name"] == "New"
    workspace.refresh_from_db()
    assert workspace.name == "New"


def test_bare_member_cannot_rename(organization, admin, django_user_model):
    workspace = _make_workspace(admin, organization, "Old")
    member = _user(django_user_model, "member")
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=WorkspaceRole.MEMBER.value)

    response = _client(member).patch(_detail(workspace.uuid), {"name": "New"}, format="json")

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# archive / restore
# ---------------------------------------------------------------------------


def test_archive_then_restore_round_trips(organization, admin):
    workspace = _make_workspace(admin, organization)

    archived = _client(admin).post(_detail(workspace.uuid) + "archive/")
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True

    restored = _client(admin).post(_detail(workspace.uuid) + "restore/")
    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False


# ---------------------------------------------------------------------------
# transfer ownership
# ---------------------------------------------------------------------------


def test_owner_transfers_ownership_to_a_member(organization, admin, django_user_model):
    workspace = _make_workspace(admin, organization)
    successor = _user(django_user_model, "successor")
    WorkspaceMembership.objects.create(workspace=workspace, user=successor, role=WorkspaceRole.MEMBER.value)

    response = _client(admin).post(_detail(workspace.uuid) + "transfer/", {"user_id": successor.pk}, format="json")

    assert response.status_code == 200
    assert WorkspaceMembership.objects.get(workspace=workspace, user=successor).role == WorkspaceRole.OWNER.value
    assert WorkspaceMembership.objects.get(workspace=workspace, user=admin).role == WorkspaceRole.ADMIN.value


def test_transfer_to_a_non_member_is_not_found(organization, admin, django_user_model):
    workspace = _make_workspace(admin, organization)
    stranger = _user(django_user_model, "stranger")

    response = _client(admin).post(_detail(workspace.uuid) + "transfer/", {"user_id": stranger.pk}, format="json")

    assert response.status_code == 404


def test_transfer_without_user_id_is_a_validation_error(organization, admin):
    workspace = _make_workspace(admin, organization)

    response = _client(admin).post(_detail(workspace.uuid) + "transfer/", {}, format="json")

    assert response.status_code == 400


def test_unknown_workspace_uuid_is_an_opaque_denial(admin):
    response = _client(admin).get(_detail(uuid.uuid4()))

    # A workspace the actor cannot see and one that does not exist look identical.
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# egress policy (PLAT-238, #1945)
# ---------------------------------------------------------------------------


def _egress(workspace_uuid) -> str:
    return _detail(workspace_uuid) + "egress-policy/"


def test_detail_exposes_the_egress_policy(organization, admin):
    workspace = _make_workspace(admin, organization)

    body = _client(admin).get(_detail(workspace.uuid)).json()

    assert body["egress_policy"] == "status-quo"


def test_owner_sets_egress_policy_via_put(organization, admin):
    workspace = _make_workspace(admin, organization)

    response = _client(admin).put(_egress(workspace.uuid), {"egress_policy": "none"}, format="json")

    assert response.status_code == 200
    assert response.json()["egress_policy"] == "none"
    workspace.refresh_from_db()
    assert workspace.egress_policy == "none"


def test_bare_member_cannot_set_egress_policy(organization, admin, django_user_model):
    workspace = _make_workspace(admin, organization)
    member = _user(django_user_model, "egress-member")
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=WorkspaceRole.MEMBER.value)

    response = _client(member).put(_egress(workspace.uuid), {"egress_policy": "none"}, format="json")

    assert response.status_code == 403
    workspace.refresh_from_db()
    assert workspace.egress_policy == "status-quo"


def test_set_egress_policy_rejects_a_deployment_only_mode(organization, admin):
    workspace = _make_workspace(admin, organization)

    response = _client(admin).put(_egress(workspace.uuid), {"egress_policy": "deny-all"}, format="json")

    assert response.status_code == 400
    workspace.refresh_from_db()
    assert workspace.egress_policy == "status-quo"


def test_set_egress_policy_rejects_an_unknown_field(organization, admin):
    workspace = _make_workspace(admin, organization)

    response = _client(admin).put(
        _egress(workspace.uuid),
        {"egress_policy": "none", "allowed_cidrs": ["10.0.0.0/8"]},
        format="json",
    )

    assert response.status_code == 400
    workspace.refresh_from_db()
    assert workspace.egress_policy == "status-quo"


def test_set_egress_policy_on_unknown_workspace_is_opaque(admin):
    response = _client(admin).put(_egress(uuid.uuid4()), {"egress_policy": "none"}, format="json")

    assert response.status_code == 403
