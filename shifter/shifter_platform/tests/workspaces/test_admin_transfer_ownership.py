"""Tests for the platform-admin workspace-ownership offboarding override (#1943).

Exercises ``workspaces.services.admin_transfer_workspace_ownership`` (ADR-046-R13):
non-personal workspaces the source owns move to a replacement who already holds a
membership; non-member workspaces are reported blocked; personal workspaces are
excluded; the last-owner invariant holds (replacement promoted before source
demoted).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix: str) -> User:
    return User.objects.create_user(username=f"u{suffix}", email=f"u{suffix}@example.com")


def _org(name: str = "Org") -> Organization:
    return Organization.objects.create(name=name)


def _audit(actor: User) -> services.WorkspaceAuditContext:
    return services.WorkspaceAuditContext(actor_type="user", actor_id=actor.pk)


def _member(workspace: Workspace, user: User, role: str) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


def test_transfers_owned_workspace_to_member_replacement():
    org = _org()
    source, replacement, actor = _user("s"), _user("r"), _user("a")
    ws = Workspace.objects.create(organization=org, name="Blue")
    _member(ws, source, WorkspaceRole.OWNER.value)
    _member(ws, replacement, WorkspaceRole.MEMBER.value)

    results = services.admin_transfer_workspace_ownership(
        source_user_id=source.id, new_owner_user_id=replacement.id, audit=_audit(actor)
    )

    assert [r.outcome for r in results] == ["transferred"]
    assert WorkspaceMembership.objects.get(workspace=ws, user=replacement).role == WorkspaceRole.OWNER.value
    assert WorkspaceMembership.objects.get(workspace=ws, user=source).role == WorkspaceRole.ADMIN.value


def test_blocks_workspace_where_replacement_is_not_a_member():
    org = _org()
    source, replacement, actor = _user("s"), _user("r"), _user("a")
    ws = Workspace.objects.create(organization=org, name="Red")
    _member(ws, source, WorkspaceRole.OWNER.value)

    results = services.admin_transfer_workspace_ownership(
        source_user_id=source.id, new_owner_user_id=replacement.id, audit=_audit(actor)
    )

    assert [r.outcome for r in results] == ["blocked_no_membership"]
    # Source remains owner; nothing rehomed or fabricated.
    assert WorkspaceMembership.objects.get(workspace=ws, user=source).role == WorkspaceRole.OWNER.value
    assert not WorkspaceMembership.objects.filter(workspace=ws, user=replacement).exists()


def test_excludes_personal_workspace():
    org = _org()
    source, replacement, actor = _user("s"), _user("r"), _user("a")
    personal = Workspace.objects.create(organization=org, name="Personal", personal_for_user=source)
    _member(personal, source, WorkspaceRole.OWNER.value)
    _member(personal, replacement, WorkspaceRole.MEMBER.value)

    results = services.admin_transfer_workspace_ownership(
        source_user_id=source.id, new_owner_user_id=replacement.id, audit=_audit(actor)
    )

    assert results == []
    assert WorkspaceMembership.objects.get(workspace=personal, user=source).role == WorkspaceRole.OWNER.value


def test_replacement_already_owner_still_demotes_source():
    # Even when the replacement already owns the workspace, the departing source
    # must be demoted so it no longer owns the workspace (cycle-2 F1).
    org = _org()
    source, replacement, actor = _user("s"), _user("r"), _user("a")
    ws = Workspace.objects.create(organization=org, name="Green")
    _member(ws, source, WorkspaceRole.OWNER.value)
    _member(ws, replacement, WorkspaceRole.OWNER.value)

    results = services.admin_transfer_workspace_ownership(
        source_user_id=source.id, new_owner_user_id=replacement.id, audit=_audit(actor)
    )

    assert [r.outcome for r in results] == ["transferred"]
    assert WorkspaceMembership.objects.get(workspace=ws, user=replacement).role == WorkspaceRole.OWNER.value
    assert WorkspaceMembership.objects.get(workspace=ws, user=source).role == WorkspaceRole.ADMIN.value


def test_same_user_rejected():
    source, actor = _user("s"), _user("a")
    audit = _audit(actor)
    with pytest.raises(services.WorkspaceLifecycleError):
        services.admin_transfer_workspace_ownership(source_user_id=source.id, new_owner_user_id=source.id, audit=audit)
