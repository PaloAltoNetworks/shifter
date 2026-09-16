"""Behavior tests for the current-principal workspace context projection (#1938).

Drives ``workspaces.services.list_actor_workspace_contexts`` against real rows.
The read is a side-effect-free projection of the caller's existing memberships;
these tests go red if it starts mutating tenancy, collapses multiple
organizations into one, or derives capabilities from anything but the central
role-to-operation policy.
"""

import pytest
from django.contrib.auth import get_user_model

from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole, role_permits

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix="a"):
    return User.objects.create_user(username=f"wsctx-{suffix}@e.com", email=f"wsctx-{suffix}@e.com")


def _workspace(org_name, ws_name, *, personal_for=None):
    return Workspace.objects.create(
        organization=Organization.objects.create(name=org_name),
        name=ws_name,
        personal_for_user=personal_for,
    )


def _membership(workspace, user, role):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


def test_no_membership_yields_empty_projection():
    user = _user()

    assert services.list_actor_workspace_contexts(user) == []


def test_projection_carries_org_workspace_role_and_personal_marker():
    user = _user()
    workspace = _workspace("Acme", "Blue", personal_for=user)
    _membership(workspace, user, WorkspaceRole.OWNER)

    contexts = services.list_actor_workspace_contexts(user)

    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.organization.uuid == workspace.organization.uuid
    assert ctx.organization.name == "Acme"
    assert ctx.workspace_uuid == workspace.uuid
    assert ctx.workspace_name == "Blue"
    assert ctx.is_personal is True
    assert ctx.role == WorkspaceRole.OWNER.value


def test_projection_spans_multiple_organizations():
    user = _user()
    ws_a = _workspace("Acme", "Blue")
    ws_b = _workspace("Beta", "Green")
    _membership(ws_a, user, WorkspaceRole.MEMBER)
    _membership(ws_b, user, WorkspaceRole.ADMIN)

    contexts = services.list_actor_workspace_contexts(user)

    orgs = {ctx.organization.name for ctx in contexts}
    assert orgs == {"Acme", "Beta"}
    assert len(contexts) == 2
    # Ordered by organization name then workspace name (deterministic switcher order).
    assert [ctx.organization.name for ctx in contexts] == ["Acme", "Beta"]


def test_only_the_actors_own_memberships_are_returned():
    user = _user("self")
    other = _user("other")
    mine = _workspace("Acme", "Mine")
    theirs = _workspace("Acme", "Theirs")
    _membership(mine, user, WorkspaceRole.MEMBER)
    _membership(theirs, other, WorkspaceRole.OWNER)

    contexts = services.list_actor_workspace_contexts(user)

    assert [ctx.workspace_name for ctx in contexts] == ["Mine"]


@pytest.mark.parametrize("role", WorkspaceRole.values)
def test_capabilities_match_central_role_policy(role):
    user = _user()
    workspace = _workspace("Acme", "Blue")
    _membership(workspace, user, role)

    ctx = services.list_actor_workspace_contexts(user)[0]

    expected = {op for op in WorkspaceOperation.values if role_permits(role, op)}
    assert set(ctx.capabilities) == expected
    # A member never advertises membership-management capabilities it lacks.
    if role == WorkspaceRole.MEMBER.value:
        assert WorkspaceOperation.ADD_MEMBER.value not in ctx.capabilities
        assert WorkspaceOperation.CHANGE_MEMBER_ROLE.value not in ctx.capabilities


def test_read_is_side_effect_free():
    user = _user()
    workspace = _workspace("Acme", "Blue")
    _membership(workspace, user, WorkspaceRole.MEMBER)
    org_count = Organization.objects.count()
    ws_count = Workspace.objects.count()
    membership_count = WorkspaceMembership.objects.count()

    services.list_actor_workspace_contexts(user)

    assert Organization.objects.count() == org_count
    assert Workspace.objects.count() == ws_count
    assert WorkspaceMembership.objects.count() == membership_count
    # A staff caller with no membership never gets a personal workspace manufactured.
    staff = _user("staff")
    assert services.list_actor_workspace_contexts(staff) == []
    assert Workspace.objects.filter(personal_for_user=staff).count() == 0
