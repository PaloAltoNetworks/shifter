"""USE_CTF_COMMUNICATIONS tenancy-membership operation (ADR-051, #2048).

The operation proves active-workspace membership only; it never grants CTF event
or recipient authority. It is granted to every workspace role but, unlike the
resource operations, is denied on an archived workspace. These tests go red if
either rule is removed.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from workspaces import services
from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole, role_permits

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix="a"):
    return User.objects.create_user(username=f"ctfcomm-{suffix}@e.com", email=f"ctfcomm-{suffix}@e.com")


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER])
def test_every_role_may_use_ctf_communications(role):
    # Tenancy-membership proof only: every defined role can prove it, so a
    # legitimate member of any role can author/read communications scoped to the
    # workspace. Event and recipient authority is decided separately in CTF.
    assert role_permits(role.value, WorkspaceOperation.USE_CTF_COMMUNICATIONS.value)


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER])
def test_member_of_active_workspace_is_authorized_for_ctf_communications(role):
    owner = _user("owner")
    actor = _user(f"actor-{role.value}")
    personal = services.resolve_personal_workspace(owner)
    WorkspaceMembership.objects.create(workspace_id=personal.workspace_id, user=actor, role=role.value)

    result = services.authorize_workspace(actor, personal.workspace_uuid, WorkspaceOperation.USE_CTF_COMMUNICATIONS)

    assert result.role == role.value


def test_ctf_communications_is_denied_on_an_archived_workspace():
    user = _user()
    personal = services.resolve_personal_workspace(user)
    Workspace.objects.filter(pk=personal.workspace_id).update(archived_at=timezone.now())

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_workspace(user, personal.workspace_uuid, WorkspaceOperation.USE_CTF_COMMUNICATIONS)


def test_ctf_communications_is_denied_on_an_archived_bound_workspace():
    user = _user()
    personal = services.resolve_personal_workspace(user)
    Workspace.objects.filter(pk=personal.workspace_id).update(archived_at=timezone.now())

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.authorize_bound_workspace(user, personal.workspace_id, WorkspaceOperation.USE_CTF_COMMUNICATIONS)


def test_archive_rule_is_scoped_to_active_workspace_operations_only():
    # A resource operation on an archived workspace keeps its existing behavior;
    # the new active-workspace rule must not silently change unrelated operations.
    user = _user()
    personal = services.resolve_personal_workspace(user)
    Workspace.objects.filter(pk=personal.workspace_id).update(archived_at=timezone.now())

    result = services.authorize_workspace(user, personal.workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)

    assert result.role == WorkspaceRole.OWNER.value
