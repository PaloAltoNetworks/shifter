"""Behavior tests for the workspaces service facade (ADR-046, issue #1325).

Drives the real service against real rows. The authorization tests exist to go
red if the enforcement is removed: each one asks the seam a question a caller
would ask and asserts the *effect* (allowed / denied), not that a helper was
called.
"""

import dataclasses

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from workspaces import services
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.roles import OrganizationRole, WorkspaceOperation, WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix="a"):
    return User.objects.create_user(username=f"wss-{suffix}@e.com", email=f"wss-{suffix}@e.com")


# ---------------------------------------------------------------------------
# resolve_personal_workspace
# ---------------------------------------------------------------------------


def test_resolve_personal_workspace_creates_organization_workspace_and_owner_membership():
    user = _user()

    result = services.resolve_personal_workspace(user)

    workspace = Workspace.objects.get(personal_for_user=user)
    assert result.workspace_id == workspace.pk
    assert result.workspace_uuid == workspace.uuid
    assert result.organization_id == workspace.organization_id
    assert result.role == WorkspaceRole.OWNER.value
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=user, role=WorkspaceRole.OWNER.value).exists()


def test_resolve_personal_workspace_seeds_the_user_as_its_organization_admin():
    user = _user()

    result = services.resolve_personal_workspace(user)

    # The personal organization's bootstrap admin (ADR-048) is its personal
    # workspace owner, persisted as an OrganizationMembership so authority is
    # never re-inferred from the workspace role afterwards.
    assert OrganizationMembership.objects.filter(
        organization_id=result.organization_id,
        user=user,
        role=OrganizationRole.ADMIN.value,
    ).exists()


def test_resolve_personal_workspace_is_idempotent():
    user = _user()

    first = services.resolve_personal_workspace(user)
    second = services.resolve_personal_workspace(user)

    assert first == second
    assert Workspace.objects.filter(personal_for_user=user).count() == 1
    assert Organization.objects.count() == 1
    assert WorkspaceMembership.objects.filter(user=user).count() == 1
    assert OrganizationMembership.objects.filter(user=user).count() == 1


def test_resolve_personal_workspace_refuses_a_missing_persisted_owner_membership():
    user = _user()
    result = services.resolve_personal_workspace(user)
    WorkspaceMembership.objects.filter(workspace_id=result.workspace_id, user=user).delete()

    with pytest.raises(services.WorkspaceAuthorizationError, match="Workspace access denied"):
        services.resolve_personal_workspace(user)


def test_resolve_personal_workspace_refuses_a_demoted_persisted_owner_membership():
    user = _user()
    result = services.resolve_personal_workspace(user)
    WorkspaceMembership.objects.filter(workspace_id=result.workspace_id, user=user).update(
        role=WorkspaceRole.MEMBER.value
    )

    with pytest.raises(services.WorkspaceAuthorizationError, match="Workspace access denied"):
        services.resolve_personal_workspace(user)


def test_each_user_gets_a_distinct_personal_organization_not_a_shared_default():
    first_user = _user("one")
    second_user = _user("two")

    first = services.resolve_personal_workspace(first_user)
    second = services.resolve_personal_workspace(second_user)

    assert first.workspace_id != second.workspace_id
    # ADR-046-R4: the compatibility default is per user. A shared deployment-wide
    # organization would make every install single-tenant by construction.
    assert first.organization_id != second.organization_id
    assert Organization.objects.count() == 2


def test_authorization_result_is_immutable_and_carries_no_orm_model():
    user = _user()

    result = services.resolve_personal_workspace(user)

    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.workspace_id = 999
    assert not any(isinstance(value, (Workspace, Organization)) for value in dataclasses.astuple(result))


# ---------------------------------------------------------------------------
# authorize_workspace (public UUID)
# ---------------------------------------------------------------------------


def test_member_is_authorized_for_a_permitted_operation():
    user = _user()
    personal = services.resolve_personal_workspace(user)

    result = services.authorize_workspace(user, personal.workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)

    assert result.workspace_id == personal.workspace_id
    assert result.role == WorkspaceRole.OWNER.value


def test_non_member_is_denied():
    owner = _user("owner")
    outsider = _user("outsider")
    personal = services.resolve_personal_workspace(owner)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(outsider, personal.workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)


def test_unknown_workspace_is_denied_the_same_way_a_non_member_is():
    """A denial must not disclose whether the workspace exists."""
    outsider = _user("outsider")
    owner = _user("owner")
    personal = services.resolve_personal_workspace(owner)
    unknown_uuid = "00000000-0000-4000-8000-000000000000"

    with pytest.raises(services.WorkspaceAuthorizationError) as unknown:
        services.authorize_workspace(outsider, unknown_uuid, WorkspaceOperation.LAUNCH_RANGE)
    with pytest.raises(services.WorkspaceAuthorizationError) as not_a_member:
        services.authorize_workspace(outsider, personal.workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)

    assert str(unknown.value) == str(not_a_member.value)


def test_unknown_operation_is_denied_fail_closed():
    user = _user()
    personal = services.resolve_personal_workspace(user)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(user, personal.workspace_uuid, "delete_everything")


def test_model_access_workspace_and_organization_scopes_use_public_ids_and_admin_authority():
    owner = _user("model-access-owner")
    personal = services.resolve_personal_workspace(owner)
    second = Workspace.objects.create(
        organization_id=personal.organization_id,
        name="Second",
    )

    workspace_scope = services.resolve_model_access_workspace(owner, personal.workspace_uuid)
    assert workspace_scope.workspace_id == personal.workspace_id
    assert workspace_scope.authority_reference == f"workspace:{personal.workspace_uuid}"

    organization = Organization.objects.get(pk=personal.organization_id)
    organization_scope = services.resolve_model_access_organization(owner, organization.uuid)
    assert organization_scope.workspace_ids == tuple(sorted((personal.workspace_id, second.pk)))
    assert organization_scope.authority_reference == f"organization:{organization.uuid}"


def test_model_access_workspace_scope_denies_members_and_archived_workspaces():
    owner = _user("model-access-owner-deny")
    member = _user("model-access-member-deny")
    personal = services.resolve_personal_workspace(owner)
    WorkspaceMembership.objects.create(
        workspace_id=personal.workspace_id,
        user=member,
        role=WorkspaceRole.MEMBER.value,
    )

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.resolve_model_access_workspace(member, personal.workspace_uuid)

    workspace = Workspace.objects.get(pk=personal.workspace_id)
    workspace.archived_at = timezone.now()
    workspace.save(update_fields=["archived_at"])
    with pytest.raises(services.WorkspaceAuthorizationError):
        services.resolve_model_access_workspace(owner, personal.workspace_uuid)


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER])
@pytest.mark.parametrize(
    "operation",
    [
        WorkspaceOperation.LAUNCH_RANGE,
        WorkspaceOperation.REASSIGN_RANGE,
        WorkspaceOperation.READ_RANGE,
        WorkspaceOperation.MANAGE_RANGE,
        WorkspaceOperation.ACCESS_RANGE,
        WorkspaceOperation.LEAVE_WORKSPACE,
    ],
)
def test_every_role_can_use_its_own_product_authorized_workspace_resources(role, operation):
    owner = _user("owner")
    actor = _user(f"actor-{role.value}")
    personal = services.resolve_personal_workspace(owner)
    WorkspaceMembership.objects.create(workspace_id=personal.workspace_id, user=actor, role=role.value)

    result = services.authorize_workspace(actor, personal.workspace_uuid, operation)

    assert result.role == role.value


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
@pytest.mark.parametrize(
    "operation",
    [
        WorkspaceOperation.READ_MEMBERS,
        WorkspaceOperation.ADD_MEMBER,
        WorkspaceOperation.CHANGE_MEMBER_ROLE,
        WorkspaceOperation.REMOVE_MEMBER,
    ],
)
def test_owner_and_admin_can_request_membership_management_operations(role, operation):
    owner = _user("owner")
    actor = _user(f"actor-{role.value}")
    personal = services.resolve_personal_workspace(owner)
    WorkspaceMembership.objects.create(workspace_id=personal.workspace_id, user=actor, role=role.value)

    result = services.authorize_workspace(actor, personal.workspace_uuid, operation)

    assert result.role == role.value


@pytest.mark.parametrize(
    "operation",
    [
        WorkspaceOperation.READ_MEMBERS,
        WorkspaceOperation.ADD_MEMBER,
        WorkspaceOperation.CHANGE_MEMBER_ROLE,
        WorkspaceOperation.REMOVE_MEMBER,
    ],
)
def test_member_cannot_request_membership_management_operations(operation):
    owner = _user("owner")
    member = _user("member")
    personal = services.resolve_personal_workspace(owner)
    WorkspaceMembership.objects.create(
        workspace_id=personal.workspace_id,
        user=member,
        role=WorkspaceRole.MEMBER.value,
    )

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(member, personal.workspace_uuid, operation)


def test_a_malformed_workspace_uuid_is_denied_rather_than_raising_a_value_error():
    user = _user()

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(user, "not-a-uuid", WorkspaceOperation.LAUNCH_RANGE)


def test_membership_in_one_workspace_does_not_authorize_another():
    user = _user("member")
    other_owner = _user("other")
    services.resolve_personal_workspace(user)
    other = services.resolve_personal_workspace(other_owner)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(user, other.workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)


# ---------------------------------------------------------------------------
# authorize_bound_workspace (trusted, already-persisted internal id)
# ---------------------------------------------------------------------------


def test_bound_workspace_authorization_accepts_a_member():
    user = _user()
    personal = services.resolve_personal_workspace(user)

    result = services.authorize_bound_workspace(user, personal.workspace_id, WorkspaceOperation.REASSIGN_RANGE)

    assert result.workspace_uuid == personal.workspace_uuid


def test_bound_workspace_authorization_denies_a_non_member():
    owner = _user("owner")
    outsider = _user("outsider")
    personal = services.resolve_personal_workspace(owner)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_bound_workspace(outsider, personal.workspace_id, WorkspaceOperation.REASSIGN_RANGE)


def test_bound_workspace_authorization_denies_an_unknown_binding():
    user = _user()

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_bound_workspace(user, 987654, WorkspaceOperation.REASSIGN_RANGE)


def test_bound_workspace_authorization_denies_a_null_binding():
    """A range with no persisted workspace binding is not implicitly in scope."""
    user = _user()

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_bound_workspace(user, None, WorkspaceOperation.REASSIGN_RANGE)
