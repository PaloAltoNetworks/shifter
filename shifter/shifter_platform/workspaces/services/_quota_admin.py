"""Workspace quota policy authoring and read-only usage projection (PLAT-239, #1946).

Split out of ``_quota.py`` to keep that module within the file-length budget
(Sonar S104), mirroring the ``_egress.py`` / ``_lifecycle.py`` split. This module
owns the superuser-only authoring command and the owner/admin read surface; it
shares the enforcement helpers (validation, usage counting, policy lookup, errors)
with the enforcement core in ``_quota``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from workspaces.models import (
    WORKSPACE_QUOTA_MODE_VALUES,
    WORKSPACE_QUOTA_RESOURCE_VALUES,
    Workspace,
    WorkspaceQuotaDecision,
    WorkspaceQuotaPolicy,
)
from workspaces.roles import WorkspaceOperation

from ._authorization import authorize_workspace
from ._quota import (
    WorkspaceQuotaAuditContext,
    WorkspaceQuotaError,
    _current_usage,
    _error,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

#: Bounded number of recent decision rows the usage projection returns.
_RECENT_DECISION_LIMIT = 20


@dataclass(frozen=True, slots=True)
class WorkspaceResourceUsage:
    """Immutable per-resource usage-against-limit projection."""

    resource: str
    usage: int
    limit: int | None
    mode: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaDecisionView:
    """Immutable projection of one recorded quota decision."""

    resource: str
    outcome: str
    limit: int
    mode: str
    usage_before: int
    requested_delta: int
    reason_code: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaProjection:
    """Immutable read-only quota surface: usage per resource + recent decisions."""

    workspace_uuid: UUID
    resources: tuple[WorkspaceResourceUsage, ...]
    recent_decisions: tuple[WorkspaceQuotaDecisionView, ...]


def _validate_resource(resource: object) -> str:
    """Validate a resource code against the closed vocabulary."""
    value = str(getattr(resource, "value", resource)).strip()
    if value not in WORKSPACE_QUOTA_RESOURCE_VALUES:
        raise _error(
            "quota_resource_invalid",
            "Quota resource must be one of: " + ", ".join(sorted(WORKSPACE_QUOTA_RESOURCE_VALUES)),
        )
    return value


def _validate_mode(mode: object) -> str:
    """Validate an enforcement mode against the closed vocabulary."""
    value = str(getattr(mode, "value", mode)).strip()
    if value not in WORKSPACE_QUOTA_MODE_VALUES:
        raise _error(
            "quota_mode_invalid",
            "Quota mode must be one of: " + ", ".join(sorted(WORKSPACE_QUOTA_MODE_VALUES)),
        )
    return value


def _validate_limit(limit: object) -> int:
    """Validate a non-negative integer limit (a bool is not an integer here)."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise _error("quota_limit_invalid", "Quota limit must be a non-negative integer")
    if limit < 0:
        raise _error("quota_limit_invalid", "Quota limit must be a non-negative integer")
    return limit


def _parse_workspace_uuid(workspace_uuid: str | UUID) -> UUID:
    """Parse a public workspace UUID, mapping a bad shape to a not-found outcome."""
    try:
        return workspace_uuid if isinstance(workspace_uuid, UUID) else UUID(str(workspace_uuid))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _error("quota_workspace_not_found", "Workspace not found") from exc


def _write_policy_audit(
    workspace: Workspace,
    policy: WorkspaceQuotaPolicy,
    audit: WorkspaceQuotaAuditContext,
    previous: dict[str, object] | None,
) -> None:
    """Strict-audit a quota policy change (bounded non-tenant facts only)."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.WORKSPACE,
            entity_id=workspace.pk,
            action=AuditAction.UPDATE,
            actor_type=audit.actor_type or "system",
            actor_id=audit.actor_id,
            previous_state=previous,
            new_state={
                "workspace_id": workspace.pk,
                "resource": policy.resource,
                "limit": policy.limit,
                "mode": policy.mode,
                "revision": policy.revision,
            },
            context="workspace_quota_policy",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def _usage_for(workspace_id: int, resource: str, policy: WorkspaceQuotaPolicy | None) -> WorkspaceResourceUsage:
    """Build the usage-against-limit projection for a single resource."""
    return WorkspaceResourceUsage(
        resource=resource,
        usage=_current_usage(workspace_id, resource),
        limit=policy.limit if policy else None,
        mode=policy.mode if policy else None,
    )


def set_workspace_quota_policy(
    actor: User,
    workspace_uuid: str | UUID,
    resource: str,
    limit: int,
    mode: str,
    *,
    audit: WorkspaceQuotaAuditContext,
) -> WorkspaceResourceUsage:
    """Author a workspace quota policy (superuser-only composition-root authority).

    A quota is a platform guardrail: authoring is authorized only by a superuser
    session and is never inferred from ``is_staff``, a workspace or organization
    role, a Django model permission, an API-token scope, or a provider claim. The
    policy is upserted under the workspace mutex, its ``revision`` bumped on change,
    and one strict ``shared.audit`` event written in the same transaction. A no-op
    (limit and mode unchanged) records no audit event.

    Raises:
        WorkspaceQuotaError: The actor is not a superuser, the workspace is not
            found, or the resource/mode/limit is invalid.
    """
    if not getattr(actor, "is_superuser", False):
        raise _error("quota_policy_forbidden", "Only a platform superuser may set workspace quota policy")
    resource_value = _validate_resource(resource)
    mode_value = _validate_mode(mode)
    limit_value = _validate_limit(limit)
    parsed = _parse_workspace_uuid(workspace_uuid)
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().filter(uuid=parsed).first()
        if workspace is None:
            raise _error("quota_workspace_not_found", "Workspace not found")
        policy = (
            WorkspaceQuotaPolicy.objects.select_for_update()
            .filter(workspace=workspace, resource=resource_value)
            .first()
        )
        if policy is None:
            policy = WorkspaceQuotaPolicy.objects.create(
                workspace=workspace,
                resource=resource_value,
                limit=limit_value,
                mode=mode_value,
                revision=1,
            )
            previous: dict[str, object] | None = None
        else:
            if policy.limit == limit_value and policy.mode == mode_value:
                return _usage_for(workspace.pk, resource_value, policy)
            previous = {"limit": policy.limit, "mode": policy.mode, "revision": policy.revision}
            policy.limit = limit_value
            policy.mode = mode_value
            policy.revision = policy.revision + 1
            policy.save(update_fields=["limit", "mode", "revision", "updated_at"])
        _write_policy_audit(workspace, policy, audit, previous)
        logger.info(
            "workspace quota policy set workspace_id=%s resource=%s limit=%s mode=%s actor_id=%s",
            workspace.pk,
            resource_value,
            limit_value,
            mode_value,
            getattr(actor, "pk", None),
        )
        return _usage_for(workspace.pk, resource_value, policy)


def workspace_quota_usage(actor: User, workspace_uuid: str | UUID) -> WorkspaceQuotaProjection:
    """Return the read-only quota surface for a workspace (owner/admin authorized).

    Authorized by the existing ``READ_WORKSPACE`` role operation. Returns usage
    against the configured limit for every resource (an unconfigured resource
    reports ``limit=None`` — unlimited) plus a bounded list of recent decisions so
    an administrator can see when and why a cap applied. Strictly read-only.

    Raises:
        WorkspaceAuthorizationError: The actor may not read the workspace.
    """
    authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.READ_WORKSPACE)
    workspace_id = authorization.workspace_id
    policies = {p.resource: p for p in WorkspaceQuotaPolicy.objects.filter(workspace_id=workspace_id)}
    resources = tuple(
        _usage_for(workspace_id, resource, policies.get(resource))
        for resource in sorted(WORKSPACE_QUOTA_RESOURCE_VALUES)
    )
    decisions = tuple(
        WorkspaceQuotaDecisionView(
            resource=decision.resource,
            outcome=decision.outcome,
            limit=decision.limit_at_decision,
            mode=decision.mode_at_decision,
            usage_before=decision.usage_before,
            requested_delta=decision.requested_delta,
            reason_code=decision.reason_code,
            created_at=decision.created_at,
        )
        for decision in WorkspaceQuotaDecision.objects.filter(workspace_id=workspace_id).order_by("-created_at", "-id")[
            :_RECENT_DECISION_LIMIT
        ]
    )
    return WorkspaceQuotaProjection(
        workspace_uuid=authorization.workspace_uuid,
        resources=resources,
        recent_decisions=decisions,
    )


__all__ = [
    "WorkspaceQuotaDecisionView",
    "WorkspaceQuotaError",
    "WorkspaceQuotaProjection",
    "WorkspaceResourceUsage",
    "set_workspace_quota_policy",
    "workspace_quota_usage",
]
