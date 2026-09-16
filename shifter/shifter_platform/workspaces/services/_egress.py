"""Workspace network egress policy service (PLAT-238, #1945).

Split out of ``_lifecycle.py`` to keep that module within the file-length budget
(Sonar S104). Shares the lifecycle domain helpers (locking, audit, projection,
classified errors) with the rest of ``workspaces.services``; authority is the
workspace role seam, exactly like rename/archive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.audit import AuditAction
from workspaces.models import WORKSPACE_EGRESS_POLICY_VALUES, Workspace
from workspaces.roles import WorkspaceOperation

from ._lifecycle import WorkspaceAuditContext, WorkspaceProjection, _error, _projection, _write_audit
from ._memberships import _lock_workspace_and_actor

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _validate_egress_policy(egress_policy: object) -> str:
    """Validate an egress-policy selection against the workspace-selectable subset.

    The workspace may only carry the contextual subset of the canonical
    ``installation.range_egress.RangeEgressMode`` vocabulary (``status-quo`` /
    ``none``); ``deny-all`` and ``allowlist`` are deployment-baseline-only and are
    never a workspace selection (ADR-017-R5). The service owns this invariant for
    every caller of the facade, not only the HTTP boundary.
    """
    if not isinstance(egress_policy, str):
        raise _error("egress_policy_invalid", "Egress policy must be a string")
    cleaned = egress_policy.strip()
    if cleaned not in WORKSPACE_EGRESS_POLICY_VALUES:
        raise _error(
            "egress_policy_invalid",
            "Egress policy must be one of: " + ", ".join(sorted(WORKSPACE_EGRESS_POLICY_VALUES)),
        )
    return cleaned


def set_workspace_egress_policy(
    actor: User,
    workspace_uuid: str | UUID,
    egress_policy: str,
    *,
    audit: WorkspaceAuditContext,
) -> WorkspaceProjection:
    """Set the network egress policy of a workspace under the workspace role seam.

    Owner/admin authorized (PLAT-238, #1945). Locks the workspace and re-checks the
    grant under the lock. The selection is validated against the workspace-selectable
    subset of the canonical ``RangeEgressMode`` vocabulary before the row is touched.
    A no-op (mode unchanged) records no audit event. The policy applies to launches
    linearized after the change and never mutates a running range; it takes effect
    when the CMS launch-admission seam resolves the workspace selector.

    Unlike rename/archive, personal compatibility workspaces *are* policy-capable:
    a single-user install can opt its personal workspace into zero egress. The audit
    event records the old and new mode (non-secret policy), never a tenant value.

    Raises:
        WorkspaceAuthorizationError: The actor may not set the workspace policy.
        WorkspaceLifecycleError: The egress policy value is not a valid selection.
    """
    mode = _validate_egress_policy(egress_policy)
    with transaction.atomic():
        workspace, _ = _lock_workspace_and_actor(actor, workspace_uuid, WorkspaceOperation.SET_EGRESS_POLICY)
        if workspace.egress_policy == mode:
            return _projection(workspace)
        previous = workspace.egress_policy
        workspace.egress_policy = mode
        workspace.save(update_fields=["egress_policy", "updated_at"])
        _write_audit(
            workspace,
            AuditAction.UPDATE,
            audit,
            previous_state={"workspace_id": workspace.pk, "egress_policy": previous},
            new_state={"workspace_id": workspace.pk, "egress_policy": mode},
        )
        logger.info(
            "workspace egress policy set workspace_id=%s actor_id=%s mode=%s",
            workspace.pk,
            getattr(actor, "pk", None),
            mode,
        )
        return _projection(workspace)


def workspace_egress_policy(workspace_id: int) -> str:
    """Return the stored egress selector for a trusted internal workspace id (PLAT-238).

    The CMS launch-admission seam already holds the trusted internal
    ``workspace_id`` (produced only by this service, never an HTTP caller), so this
    read takes the integer directly rather than re-resolving a public UUID. It
    returns the raw workspace selection (``status-quo`` / ``none``); combining it
    with the deployment baseline into the *effective* mode is the launch seam's
    concern (ADR-017-R5). A missing workspace is a fail-closed error rather than a
    silent compatibility default, so a dangling scope never quietly disables the
    zero-egress posture.
    """
    workspace = Workspace.objects.filter(pk=workspace_id).values_list("egress_policy", flat=True).first()
    if workspace is None:
        raise _error("workspace_not_found", "Workspace not found for egress-policy resolution")
    return str(workspace)
