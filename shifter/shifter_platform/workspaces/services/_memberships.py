"""Transactional workspace membership lifecycle (ADR-046-R8)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, NoReturn

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.log_sanitize import safe_log_fingerprint
from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole, role_permits

from ._authorization import (
    _DENIED_MESSAGE,
    WorkspaceAuthorizationError,
)
from ._quota import (
    WorkspaceQuotaAuditContext,
    WorkspaceQuotaRejected,
    admit_workspace_member_seat,
    record_workspace_quota_rejection,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)
UserModel = get_user_model()


@dataclass(frozen=True, slots=True)
class MembershipAuditContext:
    """Trusted request attribution supplied by the HTTP boundary."""

    actor_type: str
    actor_id: int | None
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipProjection:
    """Minimum immutable membership data returned across the domain boundary."""

    membership_id: int
    workspace_uuid: uuid.UUID
    user_id: int
    display_name: str
    role: str
    created_at: datetime


class WorkspaceMembershipError(Exception):
    """A safe, classified membership command outcome."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str) -> WorkspaceMembershipError:
    """Build a classified membership command error."""
    return WorkspaceMembershipError(code, message)


def _role_value(role: object) -> str:
    """Normalize and validate a workspace role value."""
    candidate = str(getattr(role, "value", role))
    if candidate not in WorkspaceRole.values:
        raise _error("invalid_role", "Invalid workspace role")
    return candidate


def _display_name(user: User) -> str:
    """Return the stable human-readable name exposed by membership projections."""
    return user.get_full_name() or user.get_username()


def _projection(membership: WorkspaceMembership) -> WorkspaceMembershipProjection:
    """Project a persisted membership into its immutable service contract."""
    return WorkspaceMembershipProjection(
        membership_id=membership.pk,
        workspace_uuid=membership.workspace.uuid,
        user_id=membership.user_id,
        display_name=_display_name(membership.user),
        role=membership.role,
        created_at=membership.created_at,
    )


def _parsed_uuid(workspace_uuid: str | uuid.UUID) -> uuid.UUID:
    """Parse a workspace UUID while preserving opaque authorization failures."""
    try:
        return workspace_uuid if isinstance(workspace_uuid, uuid.UUID) else uuid.UUID(str(workspace_uuid))
    except (AttributeError, TypeError, ValueError) as exc:
        raise WorkspaceAuthorizationError(_DENIED_MESSAGE) from exc


def _lock_workspace_and_actor(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    operation: WorkspaceOperation,
) -> tuple[Workspace, WorkspaceMembership]:
    """Lock the workspace mutex, then re-check the actor's live grant."""
    workspace = Workspace.objects.select_for_update().filter(uuid=_parsed_uuid(workspace_uuid)).first()
    if workspace is None:
        raise WorkspaceAuthorizationError(_DENIED_MESSAGE)
    actor_membership = (
        WorkspaceMembership.objects.select_for_update()
        .select_related("workspace", "user")
        .filter(workspace=workspace, user=actor)
        .first()
    )
    if actor_membership is None or not role_permits(actor_membership.role, operation.value):
        raise WorkspaceAuthorizationError(_DENIED_MESSAGE)
    return workspace, actor_membership


def _membership_state(membership: WorkspaceMembership) -> dict[str, int | str]:
    """Return the bounded membership state recorded in audit events."""
    return {
        "workspace_id": membership.workspace_id,
        "user_id": membership.user_id,
        "role": membership.role,
    }


def _write_audit(
    membership: WorkspaceMembership,
    action: AuditAction,
    audit: MembershipAuditContext,
    *,
    previous_state: dict[str, int | str] | None = None,
    new_state: dict[str, int | str] | None = None,
) -> None:
    """Write a strict membership audit event within the caller's transaction."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
            entity_id=membership.pk,
            action=action,
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            previous_state=previous_state,
            new_state=new_state,
            context="workspace_membership",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def _seat_quota_audit(audit: MembershipAuditContext) -> WorkspaceQuotaAuditContext:
    """Forward membership request attribution to the quota decision record."""
    return WorkspaceQuotaAuditContext(
        actor_type=audit.actor_type,
        actor_id=audit.actor_id,
        source_ip=audit.source_ip,
        user_agent=audit.user_agent,
        request_id=audit.request_id,
    )


def raise_member_seats_exhausted(rejected: WorkspaceQuotaRejected, audit: MembershipAuditContext) -> NoReturn:
    """Record a hard-cap seat rejection and raise the classified membership error.

    Called only from a committed path *after* the enclosing membership transaction
    has rolled back, so the rejection evidence survives while the denied membership
    insert does not (ADR-046-R10). Both membership-add paths (direct add and
    invitation acceptance) route their rejection through here.
    """
    record_workspace_quota_rejection(rejected.workspace_id, rejected.verdict, _seat_quota_audit(audit))
    raise _error("workspace_member_seats_exhausted", "The workspace has reached its member-seat limit") from None


def _require_owner_authority(actor_membership: WorkspaceMembership) -> None:
    """Require owner authority for commands that manage another owner."""
    if actor_membership.role != WorkspaceRole.OWNER.value:
        raise _error("owner_authority_required", "Only a workspace owner may manage owners")


def _require_owner_can_depart(workspace: Workspace, target: WorkspaceMembership) -> None:
    """Reject removal or demotion of a workspace's last owner."""
    if target.role != WorkspaceRole.OWNER.value:
        return
    owner_count = WorkspaceMembership.objects.filter(
        workspace=workspace,
        role=WorkspaceRole.OWNER.value,
    ).count()
    if owner_count <= 1:
        raise _error("last_owner_required", "A workspace must keep at least one owner")


def _require_not_personal_owner(workspace: Workspace, target: WorkspaceMembership) -> None:
    """Protect the immutable owner binding of a personal workspace."""
    if workspace.personal_for_user_id == target.user_id:
        raise _error("personal_workspace_protected", "Personal workspace ownership cannot be changed")


def _insert_workspace_membership(
    workspace: Workspace,
    target: User,
    role_value: str,
    audit: MembershipAuditContext,
    *,
    exact_existing_is_idempotent: bool,
) -> WorkspaceMembershipProjection:
    """Insert and strict-audit one membership under the caller-held workspace lock."""
    existing = (
        WorkspaceMembership.objects.select_for_update()
        .select_related("workspace", "user")
        .filter(workspace=workspace, user=target)
        .first()
    )
    if existing is not None:
        if exact_existing_is_idempotent and existing.role == role_value:
            return _projection(existing)
        raise _error("membership_exists", "The account already has a workspace membership")

    # A brand-new membership consumes one seat. Evaluated under the caller-held
    # workspace mutex so the count is race-safe; an admitted/warned decision is
    # recorded in this transaction, a hard cap raises WorkspaceQuotaRejected which
    # the add/accept boundary records and maps once the transaction unwinds
    # (PLAT-239, ADR-046-R10).
    admit_workspace_member_seat(workspace.pk, _seat_quota_audit(audit))

    try:
        with transaction.atomic():
            membership = WorkspaceMembership.objects.create(
                workspace=workspace,
                user=target,
                role=role_value,
            )
    except IntegrityError:
        concurrent = (
            WorkspaceMembership.objects.select_related("workspace", "user")
            .filter(workspace=workspace, user=target)
            .first()
        )
        if concurrent is not None and exact_existing_is_idempotent and concurrent.role == role_value:
            return _projection(concurrent)
        if concurrent is not None:
            raise _error("membership_exists", "The account already has a workspace membership") from None
        raise

    membership = WorkspaceMembership.objects.select_related("workspace", "user").get(pk=membership.pk)
    _write_audit(membership, AuditAction.CREATE, audit, new_state=_membership_state(membership))
    from ._model_access import invalidate_workspace_model_access

    invalidate_workspace_model_access(workspace, reason="workspace-member-added")
    logger.info(
        "workspace membership created workspace_id=%s user_id=%s role=%s",
        workspace.pk,
        target.pk,
        role_value,
    )
    return _projection(membership)


def get_self_membership(
    actor: User,
    workspace_uuid: str | uuid.UUID,
) -> WorkspaceMembershipProjection:
    """Return the actor's own effective workspace membership."""
    from ._authorization import authorize_workspace

    authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.READ_SELF_MEMBERSHIP)
    membership = (
        WorkspaceMembership.objects.select_related("workspace", "user")
        .filter(workspace_id=authorization.workspace_id, user=actor)
        .first()
    )
    if membership is None:
        raise WorkspaceAuthorizationError(_DENIED_MESSAGE)
    return _projection(membership)


def list_workspace_memberships(
    actor: User,
    workspace_uuid: str | uuid.UUID,
) -> list[WorkspaceMembershipProjection]:
    """Return an authorized workspace roster."""
    from ._authorization import authorize_workspace

    authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.READ_MEMBERS)
    memberships = (
        WorkspaceMembership.objects.select_related("workspace", "user")
        .filter(workspace_id=authorization.workspace_id)
        .order_by("user_id")
    )
    return [_projection(membership) for membership in memberships]


def add_workspace_member(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    target_email: str,
    role: object,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Add an existing active account to a non-personal workspace."""
    role_value = _role_value(role)
    try:
        with transaction.atomic():
            workspace, actor_membership = _lock_workspace_and_actor(
                actor, workspace_uuid, WorkspaceOperation.ADD_MEMBER
            )
            if workspace.personal_for_user_id is not None:
                raise _error("personal_workspace_protected", "Personal workspaces cannot have collaborators")
            if role_value == WorkspaceRole.OWNER.value:
                _require_owner_authority(actor_membership)

            targets = list(
                UserModel.objects.filter(email__iexact=target_email.strip(), is_active=True).order_by("pk")[:2]
            )
            if len(targets) != 1:
                raise _error("member_add_failed", "Active workspace member account not found")
            target = targets[0]
            return _insert_workspace_membership(
                workspace,
                target,
                role_value,
                audit,
                exact_existing_is_idempotent=True,
            )
    except WorkspaceQuotaRejected as rejected:
        raise_member_seats_exhausted(rejected, audit)


def change_workspace_member_role(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    target_user_id: int,
    role: object,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Change one membership role under the owner/admin boundary."""
    role_value = _role_value(role)
    with transaction.atomic():
        workspace, actor_membership = _lock_workspace_and_actor(
            actor,
            workspace_uuid,
            WorkspaceOperation.CHANGE_MEMBER_ROLE,
        )
        target = (
            WorkspaceMembership.objects.select_for_update()
            .select_related("workspace", "user")
            .filter(workspace=workspace, user_id=target_user_id)
            .first()
        )
        if target is None:
            raise _error("membership_not_found", "Workspace membership not found")
        _require_not_personal_owner(workspace, target)
        if target.role == WorkspaceRole.OWNER.value or role_value == WorkspaceRole.OWNER.value:
            _require_owner_authority(actor_membership)
        if target.role == role_value:
            return _projection(target)
        _require_owner_can_depart(workspace, target)

        previous = _membership_state(target)
        target.role = role_value
        target.save(update_fields=["role", "updated_at"])
        current = _membership_state(target)
        _write_audit(target, AuditAction.UPDATE, audit, previous_state=previous, new_state=current)
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(workspace, reason="workspace-member-role-changed")
        logger.info(
            "workspace membership role changed workspace_id=%s user_id=%s role=%s",
            workspace.pk,
            target.user_id,
            safe_log_fingerprint(role_value),
        )
        return _projection(target)


def remove_workspace_member(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    target_user_id: int,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Remove another member while preserving owner invariants."""
    with transaction.atomic():
        workspace, actor_membership = _lock_workspace_and_actor(
            actor,
            workspace_uuid,
            WorkspaceOperation.REMOVE_MEMBER,
        )
        target = (
            WorkspaceMembership.objects.select_for_update()
            .select_related("workspace", "user")
            .filter(workspace=workspace, user_id=target_user_id)
            .first()
        )
        if target is None:
            raise _error("membership_not_found", "Workspace membership not found")
        _require_not_personal_owner(workspace, target)
        if target.user_id == actor.pk:
            raise _error("use_leave_operation", "Use the leave operation to remove your own membership")
        if target.role == WorkspaceRole.OWNER.value:
            _require_owner_authority(actor_membership)
        _require_owner_can_depart(workspace, target)

        result = _projection(target)
        previous = _membership_state(target)
        _write_audit(target, AuditAction.DELETE, audit, previous_state=previous)
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(workspace, reason="workspace-member-removed")
        target.delete()
        logger.info(
            "workspace membership removed workspace_id=%s user_id=%s",
            workspace.pk,
            target_user_id,
        )
        return result


def leave_workspace(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Remove the actor's own membership while preserving owner invariants."""
    with transaction.atomic():
        workspace, actor_membership = _lock_workspace_and_actor(
            actor,
            workspace_uuid,
            WorkspaceOperation.LEAVE_WORKSPACE,
        )
        _require_not_personal_owner(workspace, actor_membership)
        _require_owner_can_depart(workspace, actor_membership)
        result = _projection(actor_membership)
        previous = _membership_state(actor_membership)
        _write_audit(actor_membership, AuditAction.DELETE, audit, previous_state=previous)
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(workspace, reason="workspace-member-left")
        actor_membership.delete()
        logger.info(
            "workspace membership left workspace_id=%s user_id=%s",
            workspace.pk,
            actor.pk,
        )
        return result
