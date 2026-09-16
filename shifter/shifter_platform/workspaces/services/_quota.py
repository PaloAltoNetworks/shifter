"""Workspace resource-quota enforcement primitives (PLAT-239, #1946).

Enforcement core behind the ``workspaces.services`` facade, within the boundaries
fixed by ADR-046-R10 and
``docs/architecture/workspace-resource-quotas-preflight-1946.md``. The
superuser-only policy authoring and the owner/admin read surface live in
``_quota_admin`` (split for the Sonar S104 file-length budget).

The **enforcement primitives** evaluate a resource under the *caller-held*
workspace mutex, record every configured-policy decision as append-only evidence,
and return a bounded :class:`QuotaVerdict`. A hard-cap rejection is signalled with
:class:`WorkspaceQuotaRejected` *without* writing the rejection row, so the caller
records the evidence after its transaction unwinds — a hard rejection must commit
its decision without committing the denied action.

Missing policy means unlimited (compatibility); no decision is recorded for an
unlimited resource. Enforcement mode reuses ``shared.capacity.EnforcementMode``
terms only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from workspaces.models import (
    QUOTA_MODE_ENFORCING,
    QUOTA_OUTCOME_ADMITTED,
    QUOTA_OUTCOME_REJECTED,
    QUOTA_OUTCOME_WARNED,
    QUOTA_RESOURCE_CONCURRENT_RANGES,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Workspace,
    WorkspaceMembership,
    WorkspaceQuotaDecision,
    WorkspaceQuotaPolicy,
    WorkspaceQuotaReservation,
)

logger = logging.getLogger(__name__)

#: Correlation keys are stored in a bounded column; clip defensively.
_CORRELATION_KEY_MAX = 64


class WorkspaceQuotaError(Exception):
    """A safe, classified quota command outcome (validation/authority/not-found)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str) -> WorkspaceQuotaError:
    """Build a classified quota command error."""
    return WorkspaceQuotaError(code, message)


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaAuditContext:
    """Trusted attribution for a quota decision, supplied by the calling boundary.

    Matches the field shape of the other workspace audit contexts so a membership
    or lifecycle caller can forward its own attribution unchanged.
    """

    actor_type: str
    actor_id: int | None
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class QuotaVerdict:
    """Bounded verdict of one quota evaluation. Scalars only."""

    resource: str
    outcome: str
    usage_before: int
    limit: int | None
    mode: str | None
    reason_code: str
    policy_revision: int = 0

    @property
    def rejected(self) -> bool:
        """Whether a hard cap rejected the action."""
        return self.outcome == QUOTA_OUTCOME_REJECTED


class WorkspaceQuotaRejected(Exception):
    """Internal control-flow: a hard cap rejected the action under the caller's lock.

    Carries the :class:`QuotaVerdict` so the caller records the rejection decision
    *after* its transaction unwinds. Never raise this inside a block that would
    roll the evidence back; the rejection row is written by
    :func:`record_workspace_quota_rejection` on the committed path.
    """

    def __init__(self, verdict: QuotaVerdict, workspace_id: int) -> None:
        super().__init__(verdict.reason_code)
        self.verdict = verdict
        self.workspace_id = workspace_id


# ---------------------------------------------------------------------------
# Usage + evaluation
# ---------------------------------------------------------------------------


def _lock_workspace_row(workspace_id: int) -> None:
    """Take the workspace row mutex so the usage count that follows is race-safe.

    Both production enforcement callers already hold this lock in the same
    transaction (membership add/accept and the CMS launch-admission seam), so this
    re-acquire is reentrant and free there; taking it here makes the primitive's
    race-safety contract self-enforcing rather than caller-dependent.
    """
    Workspace.objects.select_for_update().filter(pk=workspace_id).first()


def _current_usage(workspace_id: int, resource: str) -> int:
    """Return the current authoritative usage for a resource.

    Seat usage is the canonical membership count; concurrent-range usage is the
    number of *open* reservations. Callers of the enforcement primitives hold the
    workspace mutex, so this count is race-safe in those paths.
    """
    if resource == QUOTA_RESOURCE_MEMBER_SEATS:
        return WorkspaceMembership.objects.filter(workspace_id=workspace_id).count()
    if resource == QUOTA_RESOURCE_CONCURRENT_RANGES:
        return WorkspaceQuotaReservation.objects.filter(
            workspace_id=workspace_id,
            resource=QUOTA_RESOURCE_CONCURRENT_RANGES,
            released_at__isnull=True,
        ).count()
    raise _error("quota_resource_invalid", "Unknown quota resource")


def _policy_for(workspace_id: int, resource: str) -> WorkspaceQuotaPolicy | None:
    """Return the configured policy for a resource, or ``None`` (unlimited)."""
    return WorkspaceQuotaPolicy.objects.filter(workspace_id=workspace_id, resource=resource).first()


def _evaluate(resource: str, usage_before: int, policy: WorkspaceQuotaPolicy | None, *, delta: int = 1) -> QuotaVerdict:
    """Compute the bounded verdict for a resource given usage, policy, and delta."""
    if policy is None:
        return QuotaVerdict(resource, QUOTA_OUTCOME_ADMITTED, usage_before, None, None, "no_policy")
    if usage_before + delta <= policy.limit:
        outcome, reason = QUOTA_OUTCOME_ADMITTED, "within_limit"
    elif policy.mode == QUOTA_MODE_ENFORCING:
        outcome, reason = QUOTA_OUTCOME_REJECTED, "hard_cap_exhausted"
    else:
        outcome, reason = QUOTA_OUTCOME_WARNED, "soft_cap_exceeded"
    return QuotaVerdict(resource, outcome, usage_before, policy.limit, policy.mode, reason, policy.revision)


def _write_quota_audit(workspace_id: int, verdict: QuotaVerdict, audit: WorkspaceQuotaAuditContext) -> None:
    """Emit a strict shared-audit event for an applied (warned/rejected) limit."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.WORKSPACE,
            entity_id=workspace_id,
            action=AuditAction.QUOTA_APPLIED,
            actor_type=audit.actor_type or "system",
            actor_id=audit.actor_id,
            new_state={
                "resource": verdict.resource,
                "outcome": verdict.outcome,
                "limit": verdict.limit,
                "usage_before": verdict.usage_before,
                "mode": verdict.mode,
            },
            context="workspace_quota",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def _record_decision(
    workspace_id: int,
    verdict: QuotaVerdict,
    correlation_key: str,
    audit: WorkspaceQuotaAuditContext,
    *,
    delta: int = 1,
) -> None:
    """Record one append-only decision row; project warnings/rejections to audit.

    Only configured-policy evaluations are recorded (an unlimited resource has no
    policy and no decision). ``limit`` and ``mode`` are set together, so the
    None-check narrows both for the persisted row.
    """
    if verdict.limit is None or verdict.mode is None:
        return
    WorkspaceQuotaDecision.objects.create(
        workspace_id=workspace_id,
        resource=verdict.resource,
        limit_at_decision=verdict.limit,
        mode_at_decision=verdict.mode,
        policy_revision=verdict.policy_revision,
        usage_before=verdict.usage_before,
        requested_delta=delta,
        outcome=verdict.outcome,
        reason_code=verdict.reason_code,
        actor_type=audit.actor_type or "",
        actor_id=audit.actor_id,
        correlation_key=(correlation_key or "")[:_CORRELATION_KEY_MAX],
    )
    if verdict.outcome in (QUOTA_OUTCOME_WARNED, QUOTA_OUTCOME_REJECTED):
        _write_quota_audit(workspace_id, verdict, audit)


# ---------------------------------------------------------------------------
# Enforcement primitives (caller holds the workspace mutex)
# ---------------------------------------------------------------------------


def admit_workspace_member_seat(
    workspace_id: int,
    audit: WorkspaceQuotaAuditContext,
    *,
    correlation_key: str = "",
) -> QuotaVerdict:
    """Evaluate the member-seat quota for adding one member (PLAT-239).

    MUST be called under the workspace mutex (both membership-add paths hold it).
    An admitted or warned decision is recorded inline, committed with the caller's
    membership insert. A hard cap raises :class:`WorkspaceQuotaRejected` without
    writing, so the caller records the rejection after its transaction unwinds and
    the membership is never created.
    """
    _lock_workspace_row(workspace_id)
    policy = _policy_for(workspace_id, QUOTA_RESOURCE_MEMBER_SEATS)
    usage = _current_usage(workspace_id, QUOTA_RESOURCE_MEMBER_SEATS)
    verdict = _evaluate(QUOTA_RESOURCE_MEMBER_SEATS, usage, policy)
    if verdict.rejected:
        raise WorkspaceQuotaRejected(verdict, workspace_id)
    _record_decision(workspace_id, verdict, correlation_key, audit)
    return verdict


def reserve_workspace_concurrent_range(
    workspace_id: int,
    correlation_key: str | UUID,
    audit: WorkspaceQuotaAuditContext,
) -> QuotaVerdict:
    """Reserve one concurrent-range slot under the workspace mutex (PLAT-239, ADR-046-R10).

    Idempotent on ``correlation_key``: a replay returns an admitted verdict without
    double-counting or re-deciding. An admitted or warned decision is recorded and
    the open reservation created inline, committed with the caller's CMS range
    reservation (so an active-range collision or any persistence failure rolls both
    back together). A hard cap raises :class:`WorkspaceQuotaRejected` without
    writing; the caller records the rejection after its transaction unwinds.
    """
    key = str(correlation_key)[:_CORRELATION_KEY_MAX]
    _lock_workspace_row(workspace_id)
    existing = WorkspaceQuotaReservation.objects.filter(
        workspace_id=workspace_id,
        resource=QUOTA_RESOURCE_CONCURRENT_RANGES,
        correlation_key=key,
    ).first()
    if existing is not None:
        usage = _current_usage(workspace_id, QUOTA_RESOURCE_CONCURRENT_RANGES)
        return QuotaVerdict(
            QUOTA_RESOURCE_CONCURRENT_RANGES, QUOTA_OUTCOME_ADMITTED, usage, None, None, "reservation_replay"
        )
    policy = _policy_for(workspace_id, QUOTA_RESOURCE_CONCURRENT_RANGES)
    usage = _current_usage(workspace_id, QUOTA_RESOURCE_CONCURRENT_RANGES)
    verdict = _evaluate(QUOTA_RESOURCE_CONCURRENT_RANGES, usage, policy)
    if verdict.rejected:
        raise WorkspaceQuotaRejected(verdict, workspace_id)
    WorkspaceQuotaReservation.objects.create(
        workspace_id=workspace_id,
        resource=QUOTA_RESOURCE_CONCURRENT_RANGES,
        correlation_key=key,
    )
    _record_decision(workspace_id, verdict, key, audit)
    return verdict


def release_workspace_concurrent_range(workspace_id: int, correlation_key: str | UUID) -> bool:
    """Idempotently release an open concurrent-range reservation on terminal convergence.

    A no-op when the reservation is absent or already released, so redelivery of a
    terminal range-status event and the ``reconcile_range_events`` backstop close
    the same reservation exactly once. Returns whether a row was released.
    """
    key = str(correlation_key)[:_CORRELATION_KEY_MAX]
    released = WorkspaceQuotaReservation.objects.filter(
        workspace_id=workspace_id,
        resource=QUOTA_RESOURCE_CONCURRENT_RANGES,
        correlation_key=key,
        released_at__isnull=True,
    ).update(released_at=timezone.now())
    return released > 0


def record_workspace_quota_rejection(
    workspace_id: int,
    verdict: QuotaVerdict,
    audit: WorkspaceQuotaAuditContext,
    *,
    correlation_key: str = "",
) -> None:
    """Record a hard-cap rejection decision in its own transaction.

    Called on the committed path after the denied action's transaction has unwound,
    so the rejection evidence survives while the denied mutation does not.
    """
    with transaction.atomic():
        _record_decision(workspace_id, verdict, correlation_key, audit)
