"""Transactional workspace lifecycle (create/list/rename/archive/transfer).

Implements PLAT-233 (#1940) behind the existing ``workspaces.services`` facade.
Two distinct authorities are enforced, never conflated (ADR-046-R8, ADR-048):

* Creating or listing workspaces for an organization requires that
  organization's persisted ``admin`` :class:`~workspaces.models.OrganizationMembership`
  authority (or a Django superuser override), resolved through
  :func:`workspaces.services._organization.resolve_administrable_organization`.
* Reading the administrative detail of, or mutating, an existing workspace is
  authorized by the workspace role seam for that exact public UUID via a new
  :class:`~workspaces.roles.WorkspaceOperation`; the operation-to-role mapping
  lives only in :mod:`workspaces.roles`.

Every mutation locks the workspace row, re-checks the live grant under the lock
(reusing :func:`workspaces.services._memberships._lock_workspace_and_actor`),
performs the change, and writes one strict, request-attributed ``shared.audit``
event in the same transaction, so an audit-write failure rolls the mutation
back. Personal compatibility workspaces are never created, renamed, archived,
restored, or ownership-transferred through this surface. Archive is a reversible
``archived_at`` marker only: it never deletes, rehomes, or cascades to the
scalar ``workspace_id`` range bindings in CMS/Engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole

from ._authorization import _DENIED_MESSAGE, WorkspaceAuthorizationError, authorize_workspace
from ._memberships import _lock_workspace_and_actor
from ._organization import resolve_administrable_organization

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

#: Matched to the ``Workspace.name`` column bound; the service owns the invariant
#: for every caller of the facade, not only the HTTP boundary (ADR-046-R12).
_MAX_NAME_LENGTH = 200


@dataclass(frozen=True, slots=True)
class WorkspaceAuditContext:
    """Trusted request attribution supplied by the HTTP boundary."""

    actor_type: str
    actor_id: int | None
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class WorkspaceProjection:
    """Immutable public workspace projection (scalars only).

    Handing another layer an ORM instance would let it mutate tenancy state
    outside this domain, so the facade returns this frozen scalar view instead.
    """

    uuid: UUID
    organization_uuid: UUID
    organization_name: str
    name: str
    is_personal: bool
    is_archived: bool
    archived_at: datetime | None
    egress_policy: str
    created_at: datetime
    updated_at: datetime


class WorkspaceLifecycleError(Exception):
    """A safe, classified workspace lifecycle command outcome."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str) -> WorkspaceLifecycleError:
    """Build a classified lifecycle command error."""
    return WorkspaceLifecycleError(code, message)


def _validate_name(name: object) -> str:
    """Validate and normalize a workspace name for every caller of the facade."""
    if not isinstance(name, str):
        raise _error("name_invalid", "Workspace name must be a string")
    cleaned = name.strip()
    if not cleaned:
        raise _error("name_blank", "Workspace name must not be blank")
    if len(cleaned) > _MAX_NAME_LENGTH:
        raise _error("name_too_long", f"Workspace name exceeds {_MAX_NAME_LENGTH} characters")
    return cleaned


def _projection(workspace: Workspace) -> WorkspaceProjection:
    """Project a workspace row onto the immutable public projection."""
    organization = workspace.organization
    return WorkspaceProjection(
        uuid=workspace.uuid,
        organization_uuid=organization.uuid,
        organization_name=organization.name,
        name=workspace.name,
        is_personal=workspace.personal_for_user_id is not None,
        is_archived=workspace.archived_at is not None,
        archived_at=workspace.archived_at,
        egress_policy=workspace.egress_policy,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _reject_personal(workspace: Workspace) -> None:
    """Protect the personal compatibility workspace from lifecycle mutation."""
    if workspace.personal_for_user_id is not None:
        raise _error(
            "personal_workspace_protected",
            "Personal workspaces cannot be managed through the lifecycle surface",
        )


def _write_audit(
    workspace: Workspace,
    action: AuditAction,
    audit: WorkspaceAuditContext,
    *,
    previous_state: dict[str, object] | None = None,
    new_state: dict[str, object] | None = None,
) -> None:
    """Write a strict workspace lifecycle audit event within the caller's transaction.

    Records internal integer IDs, the action, and bounded state/field *names*
    only -- never the workspace display name, organization name, or any other
    tenant value.
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.WORKSPACE,
            entity_id=workspace.pk,
            action=action,
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            previous_state=previous_state,
            new_state=new_state,
            context="workspace_lifecycle",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def create_workspace(
    actor: User,
    organization_uuid: str | UUID,
    name: str,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Create an ordinary workspace in an organization the actor administers.

    Organization-authorized (ADR-048 admin membership or superuser override).
    The workspace and the creator's ``OWNER`` membership are created together in
    one transaction, so a new workspace always has an owner. The name must be
    unique within the organization; a collision is a classified ``name_taken``
    outcome rather than a raw ``IntegrityError``.

    Raises:
        OrganizationAuthorizationError: The organization UUID is malformed,
            absent, or outside the actor's admin authority.
        WorkspaceLifecycleError: The name is invalid or already taken.
    """
    cleaned = _validate_name(name)
    organization, superuser_override = resolve_administrable_organization(actor, organization_uuid)
    try:
        with transaction.atomic():
            workspace = Workspace.objects.create(organization=organization, name=cleaned)
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=actor,
                role=WorkspaceRole.OWNER.value,
            )
            from ._model_access import invalidate_workspace_model_access

            invalidate_workspace_model_access(
                workspace,
                reason="workspace-created",
                include_organization=True,
            )
            _write_audit(
                workspace,
                AuditAction.CREATE,
                audit,
                new_state={
                    "workspace_id": workspace.pk,
                    "organization_id": organization.pk,
                    "superuser_override": superuser_override,
                },
            )
    except IntegrityError:
        raise _error("name_taken", "A workspace with that name already exists in the organization") from None
    logger.info(
        "workspace created workspace_id=%s organization_id=%s actor_id=%s",
        workspace.pk,
        organization.pk,
        getattr(actor, "pk", None),
    )
    return _projection(workspace)


def list_workspaces(
    actor: User,
    organization_uuid: str | UUID,
    *,
    include_archived: bool = False,
    search: str | None = None,
) -> list[WorkspaceProjection]:
    """Return the ordinary workspaces of an organization the actor administers.

    Organization-authorized. Personal compatibility workspaces are excluded --
    they are per-user scopes, not ordinary organization workspaces. Active-only
    by default; ``include_archived=True`` adds archived workspaces (the explicit
    archived-state filter). ``search`` matches the workspace name
    case-insensitively. Ordered by name for a deterministic list.

    Raises:
        OrganizationAuthorizationError: The organization UUID is malformed,
            absent, or outside the actor's admin authority.
    """
    organization, _ = resolve_administrable_organization(actor, organization_uuid)
    queryset = Workspace.objects.select_related("organization").filter(
        organization=organization,
        personal_for_user__isnull=True,
    )
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)
    if search and search.strip():
        queryset = queryset.filter(name__icontains=search.strip())
    return [_projection(workspace) for workspace in queryset.order_by("name", "id")]


def get_workspace(actor: User, workspace_uuid: str | UUID) -> WorkspaceProjection:
    """Return the administrative detail of one workspace, keyed by public UUID.

    Workspace-role authorized (owner or admin membership). A malformed UUID, an
    unknown workspace, and a workspace the actor may not read all raise the same
    opaque denial.

    Raises:
        WorkspaceAuthorizationError: The actor may not read the workspace.
    """
    authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.READ_WORKSPACE)
    workspace = Workspace.objects.select_related("organization").filter(pk=authorization.workspace_id).first()
    if workspace is None:
        # Defensive: authorize_workspace already proved a membership exists.
        raise WorkspaceAuthorizationError(_DENIED_MESSAGE)
    return _projection(workspace)


def rename_workspace(
    actor: User,
    workspace_uuid: str | UUID,
    new_name: str,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Rename a non-personal workspace under the workspace role seam.

    Owner/admin authorized. Locks the workspace and re-checks the grant under the
    lock. A no-op (name unchanged) records no audit event. A name collision is a
    classified ``name_taken`` outcome. The audit event records the changed field
    *name* only, never the old or new value.

    Raises:
        WorkspaceAuthorizationError: The actor may not rename the workspace.
        WorkspaceLifecycleError: The name is invalid, taken, or the workspace is
            personal.
    """
    cleaned = _validate_name(new_name)
    with transaction.atomic():
        workspace, _ = _lock_workspace_and_actor(actor, workspace_uuid, WorkspaceOperation.RENAME_WORKSPACE)
        _reject_personal(workspace)
        if workspace.name == cleaned:
            return _projection(workspace)
        workspace.name = cleaned
        try:
            with transaction.atomic():
                workspace.save(update_fields=["name", "updated_at"])
        except IntegrityError:
            raise _error("name_taken", "A workspace with that name already exists in the organization") from None
        _write_audit(
            workspace,
            AuditAction.UPDATE,
            audit,
            new_state={"workspace_id": workspace.pk, "changed_fields": ["name"]},
        )
        logger.info("workspace renamed workspace_id=%s actor_id=%s", workspace.pk, getattr(actor, "pk", None))
        return _projection(workspace)


def archive_workspace(
    actor: User,
    workspace_uuid: str | UUID,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Archive a non-personal workspace (reversible ``archived_at`` marker).

    Owner/admin authorized. Idempotent: archiving an already-archived workspace
    is a no-op that records no audit event. Archival sets the marker only -- it
    never deletes, rehomes, or cascades to ranges bound to the workspace.

    Raises:
        WorkspaceAuthorizationError: The actor may not archive the workspace.
        WorkspaceLifecycleError: The workspace is personal.
    """
    with transaction.atomic():
        workspace, _ = _lock_workspace_and_actor(actor, workspace_uuid, WorkspaceOperation.ARCHIVE_WORKSPACE)
        _reject_personal(workspace)
        if workspace.archived_at is not None:
            return _projection(workspace)
        workspace.archived_at = timezone.now()
        workspace.save(update_fields=["archived_at", "updated_at"])
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(
            workspace,
            reason="workspace-archived",
            include_organization=True,
        )
        _write_audit(
            workspace,
            AuditAction.ARCHIVE,
            audit,
            new_state={"workspace_id": workspace.pk, "archived": True},
        )
        logger.info("workspace archived workspace_id=%s actor_id=%s", workspace.pk, getattr(actor, "pk", None))
        return _projection(workspace)


def restore_workspace(
    actor: User,
    workspace_uuid: str | UUID,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Restore an archived non-personal workspace (clears ``archived_at``).

    Owner/admin authorized. Idempotent: restoring an active workspace is a no-op
    that records no audit event.

    Raises:
        WorkspaceAuthorizationError: The actor may not restore the workspace.
        WorkspaceLifecycleError: The workspace is personal.
    """
    with transaction.atomic():
        workspace, _ = _lock_workspace_and_actor(actor, workspace_uuid, WorkspaceOperation.RESTORE_WORKSPACE)
        _reject_personal(workspace)
        if workspace.archived_at is None:
            return _projection(workspace)
        workspace.archived_at = None
        workspace.save(update_fields=["archived_at", "updated_at"])
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(
            workspace,
            reason="workspace-restored",
            include_organization=True,
        )
        _write_audit(
            workspace,
            AuditAction.RESTORE,
            audit,
            new_state={"workspace_id": workspace.pk, "archived": False},
        )
        logger.info("workspace restored workspace_id=%s actor_id=%s", workspace.pk, getattr(actor, "pk", None))
        return _projection(workspace)


def transfer_workspace_ownership(
    actor: User,
    workspace_uuid: str | UUID,
    new_owner_user_id: int,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Transfer ownership of a non-personal workspace to an existing member.

    Owner-only authorized (``TRANSFER_OWNERSHIP`` is granted to the owner role
    alone). One atomic, locked command: it promotes the target's existing active
    membership to ``OWNER`` and demotes the acting owner to ``ADMIN``, preserving
    the last-owner invariant throughout (the target is made an owner before the
    actor steps down). Transferring to the current owner is a no-op. The target
    must already hold a membership in the workspace.

    Raises:
        WorkspaceAuthorizationError: The actor is not the workspace owner.
        WorkspaceLifecycleError: The workspace is personal or the target holds no
            membership.
    """
    with transaction.atomic():
        workspace, actor_membership = _lock_workspace_and_actor(
            actor,
            workspace_uuid,
            WorkspaceOperation.TRANSFER_OWNERSHIP,
        )
        _reject_personal(workspace)
        if new_owner_user_id == actor_membership.user_id:
            return _projection(workspace)
        target = (
            WorkspaceMembership.objects.select_for_update()
            .filter(workspace=workspace, user_id=new_owner_user_id)
            .first()
        )
        if target is None:
            raise _error("membership_not_found", "The target account is not a member of this workspace")

        previous_owner_id = actor_membership.user_id
        if target.role != WorkspaceRole.OWNER.value:
            target.role = WorkspaceRole.OWNER.value
            target.save(update_fields=["role", "updated_at"])
        actor_membership.role = WorkspaceRole.ADMIN.value
        actor_membership.save(update_fields=["role", "updated_at"])
        from ._model_access import invalidate_workspace_model_access

        invalidate_workspace_model_access(workspace, reason="workspace-owner-transferred")
        _write_audit(
            workspace,
            AuditAction.UPDATE,
            audit,
            previous_state={"workspace_id": workspace.pk, "owner_user_id": previous_owner_id},
            new_state={"workspace_id": workspace.pk, "owner_user_id": target.user_id},
        )
        logger.info(
            "workspace ownership transferred workspace_id=%s previous_owner_id=%s new_owner_id=%s",
            workspace.pk,
            previous_owner_id,
            target.user_id,
        )
        return _projection(workspace)
