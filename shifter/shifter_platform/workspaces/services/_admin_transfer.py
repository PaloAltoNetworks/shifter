"""Platform-administrator offboarding workspace-ownership transfer (ADR-046-R13).

Split out of ``_lifecycle`` to keep each module within the file-size budget. This
is the narrow override of R8's owner-only boundary: a departing user's owned
workspaces move to a replacement during offboarding. Authorization is the
composition root's responsibility (superuser session); this service is never
reachable through workspace-role authority.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from shared.audit import AuditAction
from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

from ._lifecycle import WorkspaceAuditContext, _error, _write_audit

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkspaceOwnershipTransferResult:
    """Per-workspace outcome of an administrator offboarding ownership transfer."""

    workspace_uuid: UUID
    # "transferred" | "blocked_no_membership"
    outcome: str


def admin_transfer_workspace_ownership(
    *,
    source_user_id: int,
    new_owner_user_id: int,
    audit: WorkspaceAuditContext,
) -> list[WorkspaceOwnershipTransferResult]:
    """Platform-administrator offboarding transfer of a departing user's workspaces.

    Transfers ownership of every **non-personal** workspace the source user owns
    to the replacement, as an explicit narrow override of ADR-046-R8's owner-only
    boundary accepted by **ADR-046-R13**. Authorization is the composition root's
    responsibility (superuser session); this service is never reachable through
    workspace-role authority and must not be called from a tenant-facing path.

    Per workspace, under a row lock: the replacement must already hold a
    membership (a non-member workspace is reported ``blocked_no_membership`` and
    never silently rehomed or given a fabricated membership, preserving ADR-048);
    the replacement is promoted to ``OWNER`` before the source is demoted to
    ``ADMIN`` so the last-owner invariant holds throughout; personal workspaces
    are excluded (immutable compatibility state). Every real change writes a
    strict, request-attributed audit event in the one enclosing transaction, so
    all transfers commit together or none do.

    Raises:
        WorkspaceLifecycleError: If source and replacement are the same account.
    """
    if source_user_id == new_owner_user_id:
        raise _error("same_user", "The replacement account must differ from the departing account")

    results: list[WorkspaceOwnershipTransferResult] = []
    with transaction.atomic():
        # Resolve the candidate workspace ids first, WITHOUT a row lock: locking a
        # query that joins to the nullable ``personal_for_user`` side raises
        # "FOR UPDATE cannot be applied to the nullable side of an outer join" on
        # PostgreSQL (issue #1943). Rows are locked individually inside the loop.
        candidate_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user_id=source_user_id,
                role=WorkspaceRole.OWNER.value,
                workspace__personal_for_user__isnull=True,
            )
            .order_by("workspace_id")
            .values_list("workspace_id", flat=True)
        )
        for workspace_id in candidate_workspace_ids:
            result = _transfer_one_workspace(workspace_id, source_user_id, new_owner_user_id, audit)
            if result is not None:
                results.append(result)
    return results


def _transfer_one_workspace(
    workspace_id: int,
    source_user_id: int,
    new_owner_user_id: int,
    audit: WorkspaceAuditContext,
) -> WorkspaceOwnershipTransferResult | None:
    """Transfer one locked workspace; None when ownership changed before the lock."""
    workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
    source_membership = (
        WorkspaceMembership.objects.select_for_update()
        .filter(workspace=workspace, user_id=source_user_id, role=WorkspaceRole.OWNER.value)
        .first()
    )
    if source_membership is None:
        # Ownership changed between resolution and lock; skip safely.
        return None
    target = (
        WorkspaceMembership.objects.select_for_update().filter(workspace=workspace, user_id=new_owner_user_id).first()
    )
    if target is None:
        return WorkspaceOwnershipTransferResult(workspace.uuid, "blocked_no_membership")

    # Complete the offboarding even when the replacement already owns the
    # workspace: the departing source is still an owner (only its OWNER
    # memberships are visited), so it must be demoted so it no longer owns the
    # workspace (issue #1943 review cycle-2 F1, ADR-046-R13).
    if target.role != WorkspaceRole.OWNER.value:
        target.role = WorkspaceRole.OWNER.value
        target.save(update_fields=["role", "updated_at"])
    source_membership.role = WorkspaceRole.ADMIN.value
    source_membership.save(update_fields=["role", "updated_at"])
    from ._model_access import invalidate_workspace_model_access

    invalidate_workspace_model_access(workspace, reason="workspace-owner-transferred")
    _write_audit(
        workspace,
        AuditAction.UPDATE,
        audit,
        previous_state={"workspace_id": workspace.pk, "owner_user_id": source_user_id},
        new_state={"workspace_id": workspace.pk, "owner_user_id": new_owner_user_id},
    )
    logger.info(
        "admin workspace ownership transfer workspace_id=%s from_user_id=%s to_user_id=%s",
        workspace.pk,
        source_user_id,
        new_owner_user_id,
    )
    return WorkspaceOwnershipTransferResult(workspace.uuid, "transferred")
