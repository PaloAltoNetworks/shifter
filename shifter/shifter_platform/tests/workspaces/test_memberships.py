"""Behavior tests for workspace membership lifecycle and authority (ADR-046-R8)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    bind_audit_writer,
    get_audit_writer,
    reset_audit_writer,
)
from shared.models import AuditLog
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


class _FailingAuditWriter:
    def write(self, event) -> None:
        raise RuntimeError("audit unavailable")


def _user(suffix: str):
    return User.objects.create_user(
        username=f"membership-{suffix}@example.com",
        email=f"membership-{suffix}@example.com",
    )


def _shared_workspace():
    owner = _user("owner")
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Research Lab"),
        name="Shared",
    )
    owner_membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceRole.OWNER,
    )
    return owner, workspace, owner_membership


def _add_direct(workspace, user, role: str):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


def _audit(actor) -> services.MembershipAuditContext:
    return services.MembershipAuditContext(
        actor_type=AuditActorType.USER,
        actor_id=actor.pk,
        source_ip="192.0.2.10",
        user_agent="workspace-test",
        request_id="membership-request",
    )


def _assert_error(code: str, call) -> None:
    with pytest.raises(services.WorkspaceMembershipError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("role", WorkspaceRole.values)
def test_member_can_read_own_effective_membership(role):
    owner, workspace, _ = _shared_workspace()
    actor = owner if role == WorkspaceRole.OWNER else _user(role)
    if actor != owner:
        _add_direct(workspace, actor, role)

    result = services.get_self_membership(actor, workspace.uuid)

    assert result.workspace_uuid == workspace.uuid
    assert result.user_id == actor.pk
    assert result.role == role


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_owner_and_admin_can_read_roster(role):
    owner, workspace, _ = _shared_workspace()
    actor = owner if role == WorkspaceRole.OWNER else _user("admin")
    member = _user("member")
    if actor != owner:
        _add_direct(workspace, actor, role)
    _add_direct(workspace, member, WorkspaceRole.MEMBER)

    roster = services.list_workspace_memberships(actor, workspace.uuid)

    assert {item.user_id for item in roster} == {owner.pk, actor.pk, member.pk}


def test_member_cannot_read_roster():
    _owner, workspace, _ = _shared_workspace()
    member = _user("member")
    _add_direct(workspace, member, WorkspaceRole.MEMBER)

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.list_workspace_memberships(member, workspace.uuid)


@pytest.mark.parametrize("actor_role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
@pytest.mark.parametrize("target_role", [WorkspaceRole.ADMIN, WorkspaceRole.MEMBER])
def test_owner_and_admin_can_add_non_owner_members(actor_role, target_role):
    owner, workspace, _ = _shared_workspace()
    actor = owner if actor_role == WorkspaceRole.OWNER else _user("admin")
    if actor != owner:
        _add_direct(workspace, actor, actor_role)
    target = _user(f"target-{actor_role}-{target_role}")

    result = services.add_workspace_member(
        actor,
        workspace.uuid,
        target.email,
        target_role,
        audit=_audit(actor),
    )

    assert result.user_id == target.pk
    assert result.role == target_role
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=target, role=target_role).exists()


def test_only_owner_can_grant_owner():
    owner, workspace, _ = _shared_workspace()
    admin = _user("admin")
    target = _user("target")
    _add_direct(workspace, admin, WorkspaceRole.ADMIN)

    _assert_error(
        "owner_authority_required",
        lambda: services.add_workspace_member(
            admin,
            workspace.uuid,
            target.email,
            WorkspaceRole.OWNER,
            audit=_audit(admin),
        ),
    )

    result = services.add_workspace_member(
        owner,
        workspace.uuid,
        target.email,
        WorkspaceRole.OWNER,
        audit=_audit(owner),
    )
    assert result.role == WorkspaceRole.OWNER


def test_exact_duplicate_add_is_idempotent_but_never_changes_role():
    owner, workspace, _ = _shared_workspace()
    target = _user("target")
    first = services.add_workspace_member(
        owner,
        workspace.uuid,
        target.email,
        WorkspaceRole.MEMBER,
        audit=_audit(owner),
    )
    audit_count = AuditLog.objects.count()

    duplicate = services.add_workspace_member(
        owner,
        workspace.uuid,
        target.email,
        WorkspaceRole.MEMBER,
        audit=_audit(owner),
    )

    assert duplicate == first
    assert AuditLog.objects.count() == audit_count
    _assert_error(
        "membership_exists",
        lambda: services.add_workspace_member(
            owner,
            workspace.uuid,
            target.email,
            WorkspaceRole.ADMIN,
            audit=_audit(owner),
        ),
    )
    assert WorkspaceMembership.objects.get(workspace=workspace, user=target).role == WorkspaceRole.MEMBER


def test_add_fails_closed_when_active_accounts_share_an_email():
    owner, workspace, _ = _shared_workspace()
    first = _user("duplicate-first")
    second = _user("duplicate-second")
    duplicate_email = "duplicate@example.com"
    first.email = duplicate_email
    first.save(update_fields=["email"])
    second.email = duplicate_email.upper()
    second.save(update_fields=["email"])

    workspace_uuid = workspace.uuid
    audit = _audit(owner)
    with pytest.raises(services.WorkspaceMembershipError) as exc:
        services.add_workspace_member(
            owner,
            workspace_uuid,
            duplicate_email,
            WorkspaceRole.MEMBER,
            audit=audit,
        )

    assert exc.value.code == "member_add_failed"
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user__in=[first, second]).exists()


def test_admin_can_change_member_and_admin_roles_but_not_an_owner():
    owner, workspace, _ = _shared_workspace()
    admin = _user("admin")
    target = _user("target")
    _add_direct(workspace, admin, WorkspaceRole.ADMIN)
    _add_direct(workspace, target, WorkspaceRole.MEMBER)

    result = services.change_workspace_member_role(
        admin,
        workspace.uuid,
        target.pk,
        WorkspaceRole.ADMIN,
        audit=_audit(admin),
    )
    assert result.role == WorkspaceRole.ADMIN

    _assert_error(
        "owner_authority_required",
        lambda: services.change_workspace_member_role(
            admin,
            workspace.uuid,
            owner.pk,
            WorkspaceRole.MEMBER,
            audit=_audit(admin),
        ),
    )


def test_owner_cannot_demote_the_last_owner():
    owner, workspace, _ = _shared_workspace()

    _assert_error(
        "last_owner_required",
        lambda: services.change_workspace_member_role(
            owner,
            workspace.uuid,
            owner.pk,
            WorkspaceRole.ADMIN,
            audit=_audit(owner),
        ),
    )

    second_owner = _user("second-owner")
    _add_direct(workspace, second_owner, WorkspaceRole.OWNER)
    result = services.change_workspace_member_role(
        owner,
        workspace.uuid,
        second_owner.pk,
        WorkspaceRole.ADMIN,
        audit=_audit(owner),
    )
    assert result.role == WorkspaceRole.ADMIN


def test_admin_can_remove_member_but_not_owner():
    owner, workspace, _ = _shared_workspace()
    admin = _user("admin")
    member = _user("member")
    _add_direct(workspace, admin, WorkspaceRole.ADMIN)
    _add_direct(workspace, member, WorkspaceRole.MEMBER)

    removed = services.remove_workspace_member(
        admin,
        workspace.uuid,
        member.pk,
        audit=_audit(admin),
    )
    assert removed.user_id == member.pk
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=member).exists()

    _assert_error(
        "owner_authority_required",
        lambda: services.remove_workspace_member(
            admin,
            workspace.uuid,
            owner.pk,
            audit=_audit(admin),
        ),
    )


def test_member_manager_must_use_leave_for_own_membership():
    _owner, workspace, _ = _shared_workspace()
    admin = _user("self-removing-admin")
    _add_direct(workspace, admin, WorkspaceRole.ADMIN)

    _assert_error(
        "use_leave_operation",
        lambda: services.remove_workspace_member(
            admin,
            workspace.uuid,
            admin.pk,
            audit=_audit(admin),
        ),
    )


@pytest.mark.parametrize("operation", ["change_role", "remove"])
def test_member_mutations_reject_a_target_without_membership(operation):
    owner, workspace, _ = _shared_workspace()
    nonmember = _user(f"nonmember-{operation}")

    if operation == "change_role":

        def call():
            return services.change_workspace_member_role(
                owner,
                workspace.uuid,
                nonmember.pk,
                WorkspaceRole.MEMBER,
                audit=_audit(owner),
            )
    else:

        def call():
            return services.remove_workspace_member(
                owner,
                workspace.uuid,
                nonmember.pk,
                audit=_audit(owner),
            )

    _assert_error("membership_not_found", call)


def test_member_can_leave_but_last_owner_cannot():
    owner, workspace, _ = _shared_workspace()
    member = _user("member")
    _add_direct(workspace, member, WorkspaceRole.MEMBER)

    left = services.leave_workspace(member, workspace.uuid, audit=_audit(member))
    assert left.user_id == member.pk
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=member).exists()

    _assert_error(
        "last_owner_required",
        lambda: services.leave_workspace(owner, workspace.uuid, audit=_audit(owner)),
    )


def test_personal_workspace_owner_and_roster_are_immutable():
    owner = _user("personal-owner")
    personal = services.resolve_personal_workspace(owner)
    workspace = Workspace.objects.get(pk=personal.workspace_id)
    collaborator = _user("collaborator")

    _assert_error(
        "personal_workspace_protected",
        lambda: services.add_workspace_member(
            owner,
            workspace.uuid,
            collaborator.email,
            WorkspaceRole.MEMBER,
            audit=_audit(owner),
        ),
    )
    _assert_error(
        "personal_workspace_protected",
        lambda: services.change_workspace_member_role(
            owner,
            workspace.uuid,
            owner.pk,
            WorkspaceRole.ADMIN,
            audit=_audit(owner),
        ),
    )
    _assert_error(
        "personal_workspace_protected",
        lambda: services.remove_workspace_member(
            owner,
            workspace.uuid,
            owner.pk,
            audit=_audit(owner),
        ),
    )
    _assert_error(
        "personal_workspace_protected",
        lambda: services.leave_workspace(owner, workspace.uuid, audit=_audit(owner)),
    )


def test_mutations_write_strict_sanitized_audit_rows():
    owner, workspace, _ = _shared_workspace()
    target = _user("target")

    added = services.add_workspace_member(
        owner,
        workspace.uuid,
        target.email,
        WorkspaceRole.MEMBER,
        audit=_audit(owner),
    )
    changed = services.change_workspace_member_role(
        owner,
        workspace.uuid,
        target.pk,
        WorkspaceRole.ADMIN,
        audit=_audit(owner),
    )
    services.remove_workspace_member(owner, workspace.uuid, target.pk, audit=_audit(owner))

    rows = list(
        AuditLog.objects.filter(
            entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
            entity_id=added.membership_id,
        ).order_by("timestamp")
    )
    assert [row.action for row in rows] == [AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE]
    assert rows[0].new_state == {
        "workspace_id": workspace.pk,
        "user_id": target.pk,
        "role": WorkspaceRole.MEMBER,
    }
    assert rows[1].previous_state["role"] == WorkspaceRole.MEMBER
    assert rows[1].new_state["role"] == WorkspaceRole.ADMIN
    assert rows[2].previous_state["role"] == WorkspaceRole.ADMIN
    assert all(row.actor_id == owner.pk for row in rows)
    assert all(row.request_id == "membership-request" for row in rows)
    assert target.email not in repr(rows)
    assert changed.membership_id == added.membership_id


def test_audit_failure_rolls_back_membership_change():
    owner, workspace, _ = _shared_workspace()
    target = _user("target")
    original = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(_FailingAuditWriter())
    try:
        workspace_uuid = workspace.uuid
        audit = _audit(owner)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            services.add_workspace_member(
                owner,
                workspace_uuid,
                target.email,
                WorkspaceRole.MEMBER,
                audit=audit,
            )
    finally:
        reset_audit_writer()
        bind_audit_writer(original)

    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
