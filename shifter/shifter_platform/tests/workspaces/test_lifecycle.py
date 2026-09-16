"""Behavior tests for the workspace lifecycle service (PLAT-233, issue #1940).

Drives the real service against real rows. Authorization and invariant tests
exist to go red if the enforcement is removed: each asks the seam a question a
caller would ask and asserts the effect (allowed / denied / persisted), not that
a helper was called.

Exception tests hoist the audit-context construction out of the ``pytest.raises``
block so only the call under test can raise inside it (Sonar S5778).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range
from shared.models import AuditLog
from workspaces import services
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.roles import OrganizationRole, WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix, *, is_superuser=False):
    return User.objects.create_user(
        username=f"wl-{suffix}@e.com",
        email=f"wl-{suffix}@e.com",
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def _org(name="Org"):
    return Organization.objects.create(name=name)


def _org_admin(organization, suffix="admin"):
    actor = _user(suffix)
    OrganizationMembership.objects.create(organization=organization, user=actor, role=OrganizationRole.ADMIN.value)
    return actor


def _audit(actor):
    return services.WorkspaceAuditContext(actor_type="user", actor_id=getattr(actor, "pk", None))


def _member(workspace, user, role):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------


def test_create_workspace_persists_workspace_and_seeds_creator_as_owner():
    organization = _org()
    admin = _org_admin(organization)

    result = services.create_workspace(admin, organization.uuid, "Blue Team", audit=_audit(admin))

    workspace = Workspace.objects.get(uuid=result.uuid)
    assert workspace.organization_id == organization.pk
    assert workspace.name == "Blue Team"
    assert workspace.personal_for_user_id is None
    assert result.is_personal is False
    assert result.is_archived is False
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=admin, role=WorkspaceRole.OWNER.value).exists()


def test_create_workspace_writes_a_strict_workspace_create_audit_event():
    organization = _org()
    admin = _org_admin(organization)

    result = services.create_workspace(admin, organization.uuid, "Blue Team", audit=_audit(admin))

    workspace = Workspace.objects.get(uuid=result.uuid)
    event = AuditLog.objects.get(entity_type="workspace", action="create", entity_id=workspace.pk)
    # Bounded state only: internal ids, never the display name.
    assert "Blue Team" not in (event.new_state or {}).values()


def test_create_workspace_denies_a_non_admin_of_the_organization():
    organization = _org()
    outsider = _user("outsider")
    audit = _audit(outsider)

    with pytest.raises(services.OrganizationAuthorizationError):
        services.create_workspace(outsider, organization.uuid, "Blue Team", audit=audit)
    assert not Workspace.objects.filter(name="Blue Team").exists()


def test_create_workspace_allows_a_superuser_override():
    organization = _org()
    root = _user("root", is_superuser=True)

    result = services.create_workspace(root, organization.uuid, "Blue Team", audit=_audit(root))

    assert Workspace.objects.filter(uuid=result.uuid).exists()


def test_create_workspace_rejects_a_blank_name():
    organization = _org()
    admin = _org_admin(organization)
    audit = _audit(admin)

    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.create_workspace(admin, organization.uuid, "   ", audit=audit)
    assert exc.value.code == "name_blank"


def test_create_workspace_rejects_a_duplicate_name_within_the_organization():
    organization = _org()
    admin = _org_admin(organization)
    audit = _audit(admin)
    services.create_workspace(admin, organization.uuid, "Blue Team", audit=audit)

    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.create_workspace(admin, organization.uuid, "Blue Team", audit=audit)
    assert exc.value.code == "name_taken"


def test_create_workspace_denies_an_admin_of_a_different_organization():
    organization = _org("A")
    other = _org("B")
    other_admin = _org_admin(other, "other-admin")
    audit = _audit(other_admin)

    with pytest.raises(services.OrganizationAuthorizationError):
        services.create_workspace(other_admin, organization.uuid, "Blue Team", audit=audit)


# ---------------------------------------------------------------------------
# list_workspaces
# ---------------------------------------------------------------------------


def test_list_workspaces_is_scoped_to_the_organization_and_excludes_personal():
    organization = _org("A")
    admin = _org_admin(organization)
    other = _org("B")
    services.create_workspace(admin, organization.uuid, "Alpha", audit=_audit(admin))
    # A workspace in another organization must not leak in.
    Workspace.objects.create(organization=other, name="Beta")
    # A personal workspace inside this organization must be excluded.
    personal_user = _user("personal")
    Workspace.objects.create(organization=organization, name="Personal", personal_for_user=personal_user)

    names = [w.name for w in services.list_workspaces(admin, organization.uuid)]

    assert names == ["Alpha"]


def test_list_workspaces_hides_archived_by_default_and_includes_them_on_request():
    organization = _org()
    admin = _org_admin(organization)
    services.create_workspace(admin, organization.uuid, "Active", audit=_audit(admin))
    archived = services.create_workspace(admin, organization.uuid, "Archived", audit=_audit(admin))
    services.archive_workspace(admin, archived.uuid, audit=_audit(admin))

    default_names = [w.name for w in services.list_workspaces(admin, organization.uuid)]
    all_names = [w.name for w in services.list_workspaces(admin, organization.uuid, include_archived=True)]

    assert default_names == ["Active"]
    assert all_names == ["Active", "Archived"]


def test_list_workspaces_filters_by_name_search():
    organization = _org()
    admin = _org_admin(organization)
    services.create_workspace(admin, organization.uuid, "Red Team", audit=_audit(admin))
    services.create_workspace(admin, organization.uuid, "Blue Team", audit=_audit(admin))

    names = [w.name for w in services.list_workspaces(admin, organization.uuid, search="red")]

    assert names == ["Red Team"]


def test_list_workspaces_denies_a_non_admin():
    organization = _org()
    outsider = _user("outsider")

    with pytest.raises(services.OrganizationAuthorizationError):
        services.list_workspaces(outsider, organization.uuid)


# ---------------------------------------------------------------------------
# get_workspace
# ---------------------------------------------------------------------------


def test_get_workspace_allows_an_owner_and_denies_a_bare_member():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    member = _user("member")
    _member(workspace, member, WorkspaceRole.MEMBER.value)

    owner_view = services.get_workspace(admin, created.uuid)
    assert owner_view.name == "Team"
    with pytest.raises(services.WorkspaceAuthorizationError):
        services.get_workspace(member, created.uuid)


def test_get_workspace_denies_a_non_member_with_the_opaque_error():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    outsider = _user("outsider")

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.get_workspace(outsider, created.uuid)


# ---------------------------------------------------------------------------
# rename_workspace
# ---------------------------------------------------------------------------


def test_rename_workspace_changes_the_name_for_an_owner():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Old", audit=_audit(admin))

    result = services.rename_workspace(admin, created.uuid, "New", audit=_audit(admin))

    assert result.name == "New"
    assert Workspace.objects.get(uuid=created.uuid).name == "New"


def test_rename_workspace_records_only_the_changed_field_name_not_its_value():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Old", audit=_audit(admin))

    services.rename_workspace(admin, created.uuid, "Secret Name", audit=_audit(admin))

    event = AuditLog.objects.get(entity_type="workspace", action="update", entity_id__isnull=False)
    assert event.new_state.get("changed_fields") == ["name"]
    assert "Secret Name" not in str(event.new_state)


def test_rename_workspace_denies_a_bare_member():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Old", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    member = _user("member")
    _member(workspace, member, WorkspaceRole.MEMBER.value)
    audit = _audit(member)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.rename_workspace(member, created.uuid, "New", audit=audit)
    assert Workspace.objects.get(uuid=created.uuid).name == "Old"


def test_rename_workspace_rejects_a_duplicate_name():
    organization = _org()
    admin = _org_admin(organization)
    services.create_workspace(admin, organization.uuid, "Taken", audit=_audit(admin))
    created = services.create_workspace(admin, organization.uuid, "Free", audit=_audit(admin))
    audit = _audit(admin)

    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.rename_workspace(admin, created.uuid, "Taken", audit=audit)
    assert exc.value.code == "name_taken"


def test_rename_workspace_no_op_writes_no_audit_event():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Same", audit=_audit(admin))

    services.rename_workspace(admin, created.uuid, "Same", audit=_audit(admin))

    assert not AuditLog.objects.filter(entity_type="workspace", action="update").exists()


# ---------------------------------------------------------------------------
# archive / restore
# ---------------------------------------------------------------------------


def test_archive_and_restore_toggle_the_marker_and_are_idempotent():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))

    archived = services.archive_workspace(admin, created.uuid, audit=_audit(admin))
    assert archived.is_archived is True
    assert Workspace.objects.get(uuid=created.uuid).archived_at is not None
    # Idempotent: archiving again is a no-op, not an error.
    services.archive_workspace(admin, created.uuid, audit=_audit(admin))

    restored = services.restore_workspace(admin, created.uuid, audit=_audit(admin))
    assert restored.is_archived is False
    assert Workspace.objects.get(uuid=created.uuid).archived_at is None


def test_archive_invalidates_workspace_and_organization_model_access_authority():
    from engine.models import SharingAuthorityFence
    from engine.services import publish_authority_fence

    organization = _org("Fence Org")
    admin = _org_admin(organization, "fence-admin")
    created = services.create_workspace(admin, organization.uuid, "Fence Workspace", audit=_audit(admin))
    deployment_id = "11111111-1111-4111-8111-111111111111"
    for reference in (f"workspace:{created.uuid}", f"organization:{organization.uuid}"):
        publish_authority_fence(
            deployment_id=deployment_id,
            authority_ref={"owner": "workspaces", "reference": reference},
            authority_revision=1,
            state="allowed",
        )

    services.archive_workspace(admin, created.uuid, audit=_audit(admin))

    states = {
        row.authority_reference: (row.authority_revision, row.state)
        for row in SharingAuthorityFence.objects.filter(
            deployment_id=deployment_id,
            authority_owner="workspaces",
        )
    }
    assert states[f"workspace:{created.uuid}"] == (2, "unknown")
    assert states[f"organization:{organization.uuid}"] == (2, "unknown")


def test_archive_workspace_does_not_delete_ranges_bound_to_it():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    range_owner = _user("range-owner")
    bound = Range.objects.create(workspace_id=workspace.pk, user=range_owner, status=Range.Status.READY)

    services.archive_workspace(admin, created.uuid, audit=_audit(admin))

    bound.refresh_from_db()
    # Archive is a reversible marker, never a range lifecycle operation.
    assert bound.workspace_id == workspace.pk
    assert Range.objects.filter(pk=bound.pk).exists()
    assert Workspace.objects.filter(pk=workspace.pk).exists()


def test_archive_workspace_denies_a_bare_member():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    member = _user("member")
    _member(workspace, member, WorkspaceRole.MEMBER.value)
    audit = _audit(member)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.archive_workspace(member, created.uuid, audit=audit)


# ---------------------------------------------------------------------------
# transfer_workspace_ownership
# ---------------------------------------------------------------------------


def test_transfer_ownership_promotes_target_and_demotes_the_previous_owner():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    successor = _user("successor")
    _member(workspace, successor, WorkspaceRole.MEMBER.value)

    services.transfer_workspace_ownership(admin, created.uuid, successor.pk, audit=_audit(admin))

    assert WorkspaceMembership.objects.get(workspace=workspace, user=successor).role == WorkspaceRole.OWNER.value
    assert WorkspaceMembership.objects.get(workspace=workspace, user=admin).role == WorkspaceRole.ADMIN.value
    # The last-owner invariant: the workspace still has exactly one owner.
    assert WorkspaceMembership.objects.filter(workspace=workspace, role=WorkspaceRole.OWNER.value).count() == 1


def test_transfer_ownership_is_owner_only():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    # A workspace admin (not owner) may not transfer ownership.
    non_owner = _user("wsadmin")
    _member(workspace, non_owner, WorkspaceRole.ADMIN.value)
    target = _user("target")
    _member(workspace, target, WorkspaceRole.MEMBER.value)
    audit = _audit(non_owner)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.transfer_workspace_ownership(non_owner, created.uuid, target.pk, audit=audit)
    assert WorkspaceMembership.objects.get(workspace=workspace, user=admin).role == WorkspaceRole.OWNER.value


def test_transfer_ownership_rejects_a_non_member_target():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    stranger = _user("stranger")
    audit = _audit(admin)

    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.transfer_workspace_ownership(admin, created.uuid, stranger.pk, audit=audit)
    assert exc.value.code == "membership_not_found"


# ---------------------------------------------------------------------------
# personal-workspace protection (applies to every mutation)
# ---------------------------------------------------------------------------


def test_personal_workspaces_reject_every_lifecycle_mutation():
    user = _user("personal-owner")
    authorization = services.resolve_personal_workspace(user)
    personal = Workspace.objects.get(pk=authorization.workspace_id)
    audit = _audit(user)

    with pytest.raises(services.WorkspaceLifecycleError) as rename_exc:
        services.rename_workspace(user, personal.uuid, "Renamed", audit=audit)
    assert rename_exc.value.code == "personal_workspace_protected"
    with pytest.raises(services.WorkspaceLifecycleError):
        services.archive_workspace(user, personal.uuid, audit=audit)
    with pytest.raises(services.WorkspaceLifecycleError):
        services.transfer_workspace_ownership(user, personal.uuid, user.pk, audit=audit)


# ---------------------------------------------------------------------------
# set_workspace_egress_policy (PLAT-238, #1945)
# ---------------------------------------------------------------------------


def test_workspace_defaults_to_status_quo_egress_policy():
    organization = _org()
    admin = _org_admin(organization)

    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))

    assert created.egress_policy == "status-quo"
    assert Workspace.objects.get(uuid=created.uuid).egress_policy == "status-quo"


def test_set_egress_policy_to_none_for_owner_persists_and_projects():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))

    result = services.set_workspace_egress_policy(admin, created.uuid, "none", audit=_audit(admin))

    assert result.egress_policy == "none"
    assert Workspace.objects.get(uuid=created.uuid).egress_policy == "none"


def test_set_egress_policy_allows_a_workspace_admin():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    ws_admin = _user("ws-admin")
    _member(workspace, ws_admin, WorkspaceRole.ADMIN.value)

    result = services.set_workspace_egress_policy(ws_admin, created.uuid, "none", audit=_audit(ws_admin))

    assert result.egress_policy == "none"


def test_set_egress_policy_denies_a_bare_member():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    workspace = Workspace.objects.get(uuid=created.uuid)
    member = _user("member")
    _member(workspace, member, WorkspaceRole.MEMBER.value)
    audit = _audit(member)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.set_workspace_egress_policy(member, created.uuid, "none", audit=audit)
    assert Workspace.objects.get(uuid=created.uuid).egress_policy == "status-quo"


def test_set_egress_policy_records_old_and_new_mode_audit():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))

    services.set_workspace_egress_policy(admin, created.uuid, "none", audit=_audit(admin))

    event = AuditLog.objects.get(entity_type="workspace", action="update", entity_id__isnull=False)
    assert event.previous_state.get("egress_policy") == "status-quo"
    assert event.new_state.get("egress_policy") == "none"


def test_set_egress_policy_no_op_writes_no_audit_event():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))

    services.set_workspace_egress_policy(admin, created.uuid, "status-quo", audit=_audit(admin))

    assert not AuditLog.objects.filter(entity_type="workspace", action="update").exists()


def test_set_egress_policy_rejects_a_deployment_only_mode():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    audit = _audit(admin)

    # deny-all / allowlist are deployment-baseline-only, never a workspace selection.
    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.set_workspace_egress_policy(admin, created.uuid, "deny-all", audit=audit)
    assert exc.value.code == "egress_policy_invalid"
    assert Workspace.objects.get(uuid=created.uuid).egress_policy == "status-quo"


def test_set_egress_policy_rejects_an_unknown_value():
    organization = _org()
    admin = _org_admin(organization)
    created = services.create_workspace(admin, organization.uuid, "Team", audit=_audit(admin))
    audit = _audit(admin)

    with pytest.raises(services.WorkspaceLifecycleError) as exc:
        services.set_workspace_egress_policy(admin, created.uuid, "bogus", audit=audit)
    assert exc.value.code == "egress_policy_invalid"


def test_set_egress_policy_is_allowed_on_a_personal_workspace():
    user = _user("personal-egress-owner")
    authorization = services.resolve_personal_workspace(user)
    personal = Workspace.objects.get(pk=authorization.workspace_id)

    result = services.set_workspace_egress_policy(user, personal.uuid, "none", audit=_audit(user))

    assert result.egress_policy == "none"
    assert Workspace.objects.get(pk=personal.pk).egress_policy == "none"
