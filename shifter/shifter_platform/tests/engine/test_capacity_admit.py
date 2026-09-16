"""Per-range capacity draw-down against an event budget (PLAT-201, #680).

Assessment decides and sizes a budget once per wave. Admission draws one
range's worth from that budget on every creation path -- pure database work,
no provider I/O, idempotent by ``draw_key``.

The properties that matter: a range is never admitted twice for the same
request, concurrent draws cannot exceed the budget, and released capacity comes
back. The last one is why leaks are the dangerous failure mode: a draw that is
never released refuses a future event that would actually have fit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from engine.models import CapacityDraw, CapacityReservation
from engine.services import (
    admit_range_capacity,
    reconcile_capacity_budgets,
    release_range_capacity,
)
from shared.capacity import CapacityOutcome, EnforcementMode

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(hours=1)
WINDOW_END = NOW + timedelta(hours=4)


def _budget(
    event_ref,
    *,
    committed=100.0,
    unit=10.0,
    consumed=0.0,
    metric="ec2_vcpu",
    partition="aws-dev-use2",
    enforcement=EnforcementMode.ADVISORY,
    start=WINDOW_START,
    end=WINDOW_END,
):
    """Persist one event capacity budget, as assessment would have."""
    return CapacityReservation.objects.create(
        event_ref=event_ref,
        partition_name=partition,
        metric_name=metric,
        amount=committed,
        unit_amount=unit,
        consumed=consumed,
        enforcement=enforcement.value,
        window_start=start,
        window_end=end,
    )


class TestDrawDown:
    def test_draw_within_budget_is_admitted(self):
        event_ref = uuid4()
        _budget(event_ref)

        result = admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert result.outcome is CapacityOutcome.ADMITTED
        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(10.0)

    def test_successive_draws_accumulate(self):
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0)

        for _ in range(3):
            admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(30.0)

    def test_draw_records_the_request_it_belongs_to(self):
        event_ref = uuid4()
        _budget(event_ref)
        draw_key = uuid4()

        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        assert CapacityDraw.objects.filter(draw_key=draw_key, released_at__isnull=True).count() == 1

    def test_exhausted_budget_warns_under_advisory(self):
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0, consumed=100.0)

        result = admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert result.outcome is CapacityOutcome.WARNING
        assert result.blocking is False

    def test_exhausted_budget_rejects_under_enforcing(self):
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0, consumed=100.0, enforcement=EnforcementMode.ENFORCING)

        result = admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert result.outcome is CapacityOutcome.REJECTED
        assert result.blocking is True

    def test_rejected_draw_consumes_nothing(self):
        """A refused range must not eat budget it will never use."""
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0, consumed=100.0, enforcement=EnforcementMode.ENFORCING)

        admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(100.0)
        assert CapacityDraw.objects.count() == 0

    def test_advisory_overdraw_is_recorded_so_the_overage_is_visible(self):
        """Advisory proceeds, but the draw is still booked or the ledger lies."""
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0, consumed=100.0)

        admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert CapacityDraw.objects.filter(event_ref=event_ref).count() == 1


class TestIdempotence:
    """Retries are normal on the provisioning path; they must not double-draw."""

    def test_same_request_draws_once(self):
        event_ref = uuid4()
        _budget(event_ref)
        draw_key = uuid4()

        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)
        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(10.0)
        assert CapacityDraw.objects.filter(draw_key=draw_key).count() == 1

    def test_repeat_returns_the_same_outcome(self):
        event_ref = uuid4()
        _budget(event_ref)
        draw_key = uuid4()

        first = admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)
        second = admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        assert first.outcome is second.outcome


class TestRelease:
    """Released capacity returns to the budget; leaks are the dangerous failure."""

    def test_release_returns_capacity(self):
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0)
        draw_key = uuid4()
        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        release_range_capacity(draw_key, now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(0.0)

    def test_release_is_idempotent(self):
        event_ref = uuid4()
        _budget(event_ref, committed=100.0, unit=10.0)
        draw_key = uuid4()
        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        release_range_capacity(draw_key, now=NOW)
        release_range_capacity(draw_key, now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(0.0)

    def test_release_of_unknown_request_is_a_noop(self):
        assert release_range_capacity(uuid4(), now=NOW) == 0

    def test_released_capacity_admits_the_next_range(self):
        event_ref = uuid4()
        _budget(event_ref, committed=10.0, unit=10.0, enforcement=EnforcementMode.ENFORCING)
        first = uuid4()
        admit_range_capacity(event_ref, draw_key=first, now=NOW)

        assert admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW).blocking is True
        release_range_capacity(first, now=NOW)
        assert admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW).blocking is False


class TestLedgerIntegrity:
    """The database is the backstop, not the read-then-write check."""

    def test_consumed_may_not_exceed_committed_at_the_database(self):
        event_ref = uuid4()
        budget = _budget(event_ref, committed=100.0, unit=10.0)

        budget.consumed = 150.0
        with pytest.raises(IntegrityError), transaction.atomic():
            budget.save(update_fields=["consumed"])

    def test_consumed_may_not_go_negative(self):
        event_ref = uuid4()
        budget = _budget(event_ref)

        budget.consumed = -1.0
        with pytest.raises(IntegrityError), transaction.atomic():
            budget.save(update_fields=["consumed"])


class TestNoBudget:
    """With no assessment on record the admission layer has no opinion."""

    def test_event_without_a_budget_is_not_blocked(self):
        result = admit_range_capacity(uuid4(), draw_key=uuid4(), now=NOW)

        assert result.blocking is False
        assert result.outcome is CapacityOutcome.INDETERMINATE

    def test_expired_budget_is_not_drawn_from(self):
        """A budget whose window has passed no longer describes this launch."""
        event_ref = uuid4()
        _budget(event_ref, start=NOW - timedelta(days=2), end=NOW - timedelta(days=1))

        result = admit_range_capacity(event_ref, draw_key=uuid4(), now=NOW)

        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert CapacityReservation.objects.get(event_ref=event_ref).consumed == pytest.approx(0.0)


class TestReconciliation:
    """A ledger trusted indefinitely diverges from reality."""

    def test_budgets_past_their_window_are_released(self):
        event_ref = uuid4()
        _budget(event_ref, start=NOW - timedelta(days=2), end=NOW - timedelta(days=1))

        released = reconcile_capacity_budgets(now=NOW)

        assert released == 1
        assert CapacityReservation.objects.get(event_ref=event_ref).released_at is not None

    def test_live_budgets_are_left_alone(self):
        event_ref = uuid4()
        _budget(event_ref)

        reconcile_capacity_budgets(now=NOW)

        assert CapacityReservation.objects.get(event_ref=event_ref).released_at is None

    def test_reconciliation_is_idempotent(self):
        _budget(uuid4(), start=NOW - timedelta(days=2), end=NOW - timedelta(days=1))

        reconcile_capacity_budgets(now=NOW)

        assert reconcile_capacity_budgets(now=NOW) == 0

    def test_expiring_a_budget_releases_its_open_draws(self):
        """Otherwise a draw outlives the budget it belongs to."""
        event_ref = uuid4()
        _budget(event_ref)
        draw_key = uuid4()
        admit_range_capacity(event_ref, draw_key=draw_key, now=NOW)

        reconcile_capacity_budgets(now=WINDOW_END + timedelta(seconds=1))

        assert CapacityDraw.objects.get(draw_key=draw_key).released_at is not None
