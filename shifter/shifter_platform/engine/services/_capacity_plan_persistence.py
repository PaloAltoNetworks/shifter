"""Durable side of capacity-aware admission: assessments, reservations, audit.

Split out of :mod:`engine.services._capacity_plan`, which keeps the decision
logic. Everything here writes (or reads back) the Engine-owned record of a
decision: the immutable assessment snapshot, the reservations that hold an
event's share of a metric for its window, the overlap read the decision needs,
and the bounded audit entry.

Rows carry bounded codes only -- never an observed limit, usage figure, account
identifier, or provider payload.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from shared.capacity import (
    CapacityAssessmentResult,
    CapacityOutcome,
    CapacityReasonCode,
    EnforcementMode,
    MetricVerdict,
    PartitionRef,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from engine.models import CapacityAssessment
    from shared.capacity import CapacityMetricSpec

logger = logging.getLogger(__name__)

_UNKNOWN_PARTITION = PartitionRef(
    name="",
    provider="",
    account="",
    region="",
    backend="",
)


def _committed_reservation(partition_name: str, metric_name: str, start: datetime, end: datetime) -> float:
    """Sum open reservations overlapping ``[start, end)`` for one partition metric.

    Half-open comparison: two windows that merely touch at an instant do not
    contend, but any real overlap does.
    """
    from django.db.models import Sum

    from engine.models import CapacityReservation

    total = CapacityReservation.objects.filter(
        partition_name=partition_name,
        metric_name=metric_name,
        released_at__isnull=True,
        window_start__lt=end,
        window_end__gt=start,
    ).aggregate(total=Sum("amount"))["total"]
    return float(total or 0.0)


def _persist_assessment(event_ref: UUID, result: CapacityAssessmentResult) -> CapacityAssessment:
    """Append the immutable assessment snapshot.

    Verdicts are serialized as bounded codes only -- no limit, usage, account,
    or provider payload reaches this row.
    """
    from engine.models import CapacityAssessment

    return CapacityAssessment.objects.create(
        event_ref=event_ref,
        partition_name=result.partition.name,
        policy_version=result.policy_version,
        outcome=result.outcome.value,
        observed_at=result.observed_at,
        verdicts=[
            {
                "metric": verdict.metric_name,
                "outcome": verdict.outcome.value,
                "reason_code": verdict.reason_code.value,
                "enforcement": verdict.enforcement.value,
            }
            for verdict in result.verdicts
        ],
    )


def _persist_reservations(
    assessment: CapacityAssessment,
    event_ref: UUID,
    partition_name: str,
    demand: Mapping[str, float],
    specs: Mapping[str, CapacityMetricSpec],
    start: datetime,
    end: datetime,
) -> None:
    """Commit this event's share of each declared metric for the window."""
    from engine.models import CapacityReservation

    CapacityReservation.objects.bulk_create(
        [
            CapacityReservation(
                assessment=assessment,
                event_ref=event_ref,
                partition_name=partition_name,
                metric_name=metric_name,
                amount=float(amount),
                # What one range draws when admitted, and the enforcement mode
                # in force when the budget was sized -- both pinned here so a
                # later draw reads the policy that produced the budget rather
                # than re-deriving it against drifted configuration.
                unit_amount=_unit_amount(specs[metric_name]),
                enforcement=specs[metric_name].enforcement.value,
                window_start=start,
                window_end=end,
            )
            for metric_name, amount in sorted(demand.items())
            if metric_name in specs
        ]
    )


def _unit_amount(spec: CapacityMetricSpec) -> float:
    """Return the share of a metric one range consumes.

    Derived from the same declared shape that produced the budget, so the
    per-range draw and the event total stay consistent.
    """
    if spec.per_range_cost:
        return float(spec.per_range_cost)
    return 0.0


def _record_unassessable(
    *,
    event_ref: UUID,
    partition_name: str,
    policy_version: str,
    demand: Mapping[str, float],
    now: datetime,
    reason_code: CapacityReasonCode,
) -> CapacityAssessmentResult:
    """Record an assessment that could not be performed at all.

    Still persisted, because "we could not assess this event" is exactly the
    thing an operator needs to see afterwards.
    """
    verdicts = tuple(
        MetricVerdict(
            metric_name=metric_name,
            outcome=CapacityOutcome.INDETERMINATE,
            reason_code=reason_code,
            enforcement=EnforcementMode.ADVISORY,
            observed_at=None,
        )
        for metric_name in sorted(demand)
    )
    if not verdicts:
        # An unassessable event with no costed metrics would otherwise fold to an
        # empty verdict set, and an empty set is ADMITTED. "We could not assess
        # this" must never read as "there is room", so emit the verdict
        # explicitly rather than relying on the demand map being non-empty.
        verdicts = (
            MetricVerdict(
                metric_name="",
                outcome=CapacityOutcome.INDETERMINATE,
                reason_code=reason_code,
                enforcement=EnforcementMode.ADVISORY,
                observed_at=None,
            ),
        )

    result = CapacityAssessmentResult(
        partition=replace(_UNKNOWN_PARTITION, name=partition_name),
        policy_version=policy_version,
        observed_at=now,
        verdicts=verdicts,
    )
    _persist_assessment(event_ref, result)
    return result


def _audit_assessment(assessment: CapacityAssessment, result: CapacityAssessmentResult) -> None:
    """Record the decision in the audit trail; never raises into provisioning.

    Bounded by design: the partition name, the outcome, the policy version, and
    the per-metric reason codes. No observed limit, usage figure, account
    identifier, or provider payload reaches audit free text.
    """
    try:
        from shared.audit import AuditAction, audit_log_system_event

        audit_log_system_event(
            entity_type="capacity_assessment",
            entity_id=assessment.pk,
            action=AuditAction.CAPACITY_ASSESS,
            source="engine.services.capacity",
            context=(
                f"partition={result.partition.name} outcome={result.outcome.value} "
                f"policy={result.policy_version} "
                f"codes={','.join(sorted({v.reason_code.value for v in result.verdicts}))}"
            ),
        )
    except Exception:
        logger.warning("capacity: failed to write assessment audit record")
