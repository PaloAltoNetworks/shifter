"""Per-range capacity admission: draw down an event budget (PLAT-201, #680).

Assessment and admission are deliberately separate operations with different
costs and different scopes:

- :func:`~engine.services._capacity_plan.assess_event_capacity` **decides**. It
  reads providers, computes headroom, and sizes a budget. Expensive,
  event-scoped, runs once at a wave boundary.
- :func:`admit_range_capacity` **draws**. It takes one range's share from an
  existing budget. Pure database work, per range, on every creation path.

Welding the two together is what made per-range admission impossible: calling
assessment per participant would write a fresh set of reservations each time and
an event would appear to consume its capacity once per range. Splitting them
means a late joiner, a spare, and a recovery replacement are all checked, at the
cost of a single indexed update.

This is the authorization-hold/capture shape: hold the expected total once, then
capture incrementally as ranges actually launch.

Two invariants carry the safety of the ledger:

1. **Draws are idempotent by draw key.** Provisioning retries are routine; a
   retry must not draw twice. A partial unique index enforces this against
   concurrent retries, not just sequential ones.
2. **Draws must be released.** A draw that outlives its range leaks capacity
   permanently and eventually refuses an event that would have fit. Release runs
   on teardown, and :func:`reconcile_capacity_budgets` is the backstop for
   anything that slipped.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction

from shared.capacity import (
    CapacityAssessmentResult,
    CapacityOutcome,
    CapacityReasonCode,
    EnforcementMode,
    MetricVerdict,
    PartitionRef,
)
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from engine.models import CapacityReservation

logger = logging.getLogger(__name__)


def admit_range_capacity(
    event_ref: UUID,
    *,
    draw_key: UUID,
    now: datetime | None = None,
) -> CapacityAssessmentResult:
    """Draw one range's share from ``event_ref``'s open capacity budgets.

    Returns the folded outcome. An event with no live budget yields
    ``INDETERMINATE`` and does not block: capacity planning may be disabled, or
    this range may pre-date any assessment, and neither is grounds to refuse a
    launch the operator never asked us to gate.

    Never performs provider I/O, so it is safe on the range-creation path.
    """
    from django.utils import timezone

    from engine.models import CapacityReservation

    moment = now or timezone.now()

    with transaction.atomic():
        budgets = list(
            CapacityReservation.objects.select_for_update()
            .filter(
                event_ref=event_ref,
                released_at__isnull=True,
                window_start__lte=moment,
                window_end__gt=moment,
            )
            .order_by("metric_name")
        )
        if not budgets:
            return _no_opinion(moment)

        verdicts = tuple(_draw_one(budget, draw_key=draw_key, now=moment) for budget in budgets)
        partition = _partition_of(budgets[0])

    return CapacityAssessmentResult(
        partition=partition,
        policy_version="",
        observed_at=moment,
        verdicts=verdicts,
    )


def release_range_capacity(draw_key: UUID, *, now: datetime | None = None) -> int:
    """Return one key's draws to their budgets; returns how many were released.

    Idempotent: only open draws are touched, so destroy, expiry, cancellation,
    and a retried reconciliation can all call this safely.
    """
    from django.utils import timezone

    from engine.models import CapacityDraw, CapacityReservation

    moment = now or timezone.now()
    released = 0

    with transaction.atomic():
        draws = list(CapacityDraw.objects.select_for_update().filter(draw_key=draw_key, released_at__isnull=True))
        for draw in draws:
            # Recompute rather than using an F() decrement: the check constraint
            # forbids a negative balance, so a double-booked draw from an older
            # code path would otherwise turn a release into an IntegrityError.
            CapacityReservation.objects.filter(pk=draw.reservation_id).update(
                consumed=_clamped_consumed(draw.reservation_id, draw.amount)
            )
            draw.released_at = moment
            draw.save(update_fields=["released_at"])
            released += 1
    return released


def reconcile_capacity_budgets(*, now: datetime | None = None) -> int:
    """Release budgets whose consumption window has passed.

    A ledger trusted indefinitely diverges from reality: without expiry, a
    budget from a finished event keeps consuming headroom forever. Releasing the
    budget also releases its open draws so a draw never outlives its parent.

    Returns the number of budgets released.
    """
    from django.utils import timezone

    from engine.models import CapacityDraw, CapacityReservation

    moment = now or timezone.now()

    with transaction.atomic():
        expired = list(
            CapacityReservation.objects.select_for_update().filter(
                released_at__isnull=True,
                window_end__lte=moment,
            )
        )
        if not expired:
            return 0
        ids = [budget.pk for budget in expired]
        CapacityDraw.objects.filter(reservation_id__in=ids, released_at__isnull=True).update(released_at=moment)
        CapacityReservation.objects.filter(pk__in=ids).update(released_at=moment)

    logger.info("capacity: released %d expired budget(s)", len(expired))
    return len(expired)


def _draw_one(budget: CapacityReservation, *, draw_key: UUID, now: datetime) -> MetricVerdict:
    """Take one range's share from a single budget, or explain why not."""
    from engine.models import CapacityDraw

    enforcement = _enforcement_of(budget)

    already_drawn = CapacityDraw.objects.filter(
        reservation=budget,
        draw_key=draw_key,
        released_at__isnull=True,
    ).exists()
    if already_drawn:
        # Already drawn for this key: report the same answer rather than
        # charging the budget twice for one range.
        return _verdict(budget, CapacityOutcome.ADMITTED, CapacityReasonCode.AVAILABLE, enforcement, now)

    amount = float(budget.unit_amount or 0.0)
    fits = amount <= budget.available
    if not fits and enforcement is EnforcementMode.ENFORCING:
        # A refused range must not hold budget it will never use.
        return _verdict(budget, CapacityOutcome.REJECTED, CapacityReasonCode.EXCEEDS_HEADROOM, enforcement, now)

    if fits:
        outcome, reason = CapacityOutcome.ADMITTED, CapacityReasonCode.AVAILABLE
    else:
        # Advisory proceeds, but the draw is still booked (capped at the
        # committed total by the database constraint) so the overage is visible
        # in the ledger rather than silently unaccounted.
        amount = max(0.0, budget.available)
        outcome, reason = CapacityOutcome.WARNING, CapacityReasonCode.EXCEEDS_HEADROOM

    _book(budget, draw_key=draw_key, amount=amount)
    return _verdict(budget, outcome, reason, enforcement, now)


def _book(budget: CapacityReservation, *, draw_key: UUID, amount: float) -> None:
    """Persist the draw and its budget effect inside the caller's transaction."""
    from engine.models import CapacityDraw

    try:
        with transaction.atomic():
            CapacityDraw.objects.create(
                reservation=budget,
                event_ref=budget.event_ref,
                draw_key=draw_key,
                amount=amount,
            )
            budget.consumed = budget.consumed + amount
            budget.save(update_fields=["consumed"])
    except IntegrityError:
        # A concurrent retry won the unique index, or the check constraint
        # refused an over-draw. Either way this range is already accounted for.
        logger.info("capacity: draw for key %s was already booked", safe_log_value(draw_key))


def _clamped_consumed(reservation_id: int, amount: float) -> float:
    """Return the budget's consumption with ``amount`` returned, floored at zero."""
    from engine.models import CapacityReservation

    current = CapacityReservation.objects.get(pk=reservation_id).consumed
    return max(0.0, current - amount)


def _enforcement_of(budget: CapacityReservation) -> EnforcementMode:
    """Read the enforcement mode pinned on the budget, defaulting to advisory."""
    try:
        return EnforcementMode(budget.enforcement)
    except ValueError:
        return EnforcementMode.ADVISORY


def _partition_of(budget: CapacityReservation) -> PartitionRef:
    """Build the partition identity carried on an admission result."""
    return PartitionRef(
        name=budget.partition_name,
        provider="",
        account="",
        region="",
        backend="",
    )


def _verdict(
    budget: CapacityReservation,
    outcome: CapacityOutcome,
    reason_code: CapacityReasonCode,
    enforcement: EnforcementMode,
    now: datetime,
) -> MetricVerdict:
    """Build the bounded verdict for one budget's draw."""
    return MetricVerdict(
        metric_name=budget.metric_name,
        outcome=outcome,
        reason_code=reason_code,
        enforcement=enforcement,
        observed_at=now,
    )


def _no_opinion(now: datetime) -> CapacityAssessmentResult:
    """Result for an event with no live budget: indeterminate, never blocking."""
    return CapacityAssessmentResult(
        partition=PartitionRef(name="", provider="", account="", region="", backend=""),
        policy_version="",
        observed_at=now,
        verdicts=(
            MetricVerdict(
                metric_name="",
                outcome=CapacityOutcome.INDETERMINATE,
                reason_code=CapacityReasonCode.MEASUREMENT_UNAVAILABLE,
                enforcement=EnforcementMode.ADVISORY,
                observed_at=None,
            ),
        ),
    )
