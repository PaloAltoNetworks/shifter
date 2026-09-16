"""Engine capacity assessment, reservation, and admission (PLAT-201, #680).

The Engine owns the authoritative decision. These cover the parts that are easy
to get subtly wrong: overlapping-reservation arithmetic across events, keeping
provider reads out of the transaction that reserves, not reserving capacity for
a launch that was rejected, and idempotent release.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import transaction

from engine.models import CapacityAssessment, CapacityReservation
from engine.services import EventCapacityRequest, assess_event_capacity, release_capacity_reservations
from shared.capacity import (
    CapacityOutcome,
    CapacityReasonCode,
    MeasurementSource,
    MetricObservation,
    ObservationResult,
)
from shared.capacity.catalog import load_catalog

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
WINDOW_START = NOW
WINDOW_END = NOW + timedelta(hours=4)

CATALOG_PAYLOAD = {
    "partitions": [
        {
            "name": "aws-dev-use2",
            "provider": "aws",
            "account": "111122223333",
            "region": "us-east-2",
            "backend": "ecs",
        },
        {
            "name": "aws-overflow-use2",
            "provider": "aws",
            "account": "123456789012",
            "region": "us-east-2",
            "backend": "ecs",
        },
    ],
    "metrics": [
        {
            "name": "ec2_vcpu",
            "dimension": "vcpu",
            "unit": "count",
            "partition": "aws-dev-use2",
            "source": "provider_probe",
            "freshness_seconds": 900,
            "provider_ref": {"limit_ref": "ec2/L-1216C47A", "usage_ref": "AWS/Usage/ResourceCount"},
        },
        {
            "name": "ec2_vcpu",
            "dimension": "vcpu",
            "unit": "count",
            "partition": "aws-overflow-use2",
            "source": "provider_probe",
            "freshness_seconds": 900,
            "provider_ref": {"limit_ref": "ec2/L-1216C47A", "usage_ref": "AWS/Usage/ResourceCount"},
        },
    ],
}


class FakeInventory:
    """Capacity inventory returning a fixed observation, recording call context."""

    def __init__(self, limit: float = 100.0, usage: float = 0.0, result: ObservationResult | None = None):
        self._result = result or ObservationResult(
            observation=MetricObservation(
                limit=limit,
                usage=usage,
                observed_at=NOW,
                source=MeasurementSource.PROVIDER_PROBE,
            )
        )
        self.calls = 0
        self.savepoint_depth_at_call: list[int] = []
        self.reservations_at_call: list[int] = []

    def observe(self, spec, partition):
        from engine.models import CapacityReservation

        self.calls += 1
        # pytest-django wraps every test in an outer atomic block, so
        # ``in_atomic_block`` is always True here and proves nothing. Entering
        # the service's own atomic block would push a savepoint, so a depth of
        # zero is the signal that this read is not inside it.
        self.savepoint_depth_at_call.append(len(transaction.get_connection().savepoint_ids))
        self.reservations_at_call.append(CapacityReservation.objects.count())
        return self._result


def _catalog(payload=None):
    return load_catalog(payload or CATALOG_PAYLOAD)


def _assess(
    *,
    demand: float = 10.0,
    inventory: FakeInventory | None = None,
    catalog=None,
    partition: str = "aws-dev-use2",
    event_ref=None,
    window_start=WINDOW_START,
    window_end=WINDOW_END,
):
    return assess_event_capacity(
        EventCapacityRequest(
            event_ref=event_ref or uuid4(),
            partition_name=partition,
            demand={"ec2_vcpu": demand},
            window_start=window_start,
            window_end=window_end,
        ),
        catalog=catalog or _catalog(),
        inventory=inventory or FakeInventory(),
        now=NOW,
    )


def _reserve(event_ref, *, amount, partition="aws-dev-use2", metric="ec2_vcpu", start=WINDOW_START, end=WINDOW_END):
    """Persist a committed reservation directly, standing in for another event."""
    return CapacityReservation.objects.create(
        event_ref=event_ref,
        partition_name=partition,
        metric_name=metric,
        amount=amount,
        window_start=start,
        window_end=end,
    )


class TestAdmissionOutcomes:
    def test_demand_within_headroom_is_admitted_and_reserved(self):
        result = _assess(demand=10.0)

        assert result.outcome is CapacityOutcome.ADMITTED
        assert CapacityReservation.objects.filter(released_at__isnull=True).count() == 1

    def test_advisory_over_limit_warns_and_still_proceeds(self):
        """Advisory is the default: a warning must not stop the spinup."""
        result = _assess(demand=500.0)

        assert result.outcome is CapacityOutcome.WARNING
        assert result.blocking is False
        assert CapacityReservation.objects.filter(released_at__isnull=True).count() == 1

    def test_enforcing_over_limit_rejects_and_reserves_nothing(self):
        """A rejected launch must not hold capacity it will never use."""
        payload = {
            "partitions": CATALOG_PAYLOAD["partitions"],
            "metrics": [{**CATALOG_PAYLOAD["metrics"][0], "enforcement": "enforcing"}],
        }

        result = _assess(demand=500.0, catalog=_catalog(payload))

        assert result.outcome is CapacityOutcome.REJECTED
        assert result.blocking is True
        assert CapacityReservation.objects.count() == 0

    def test_unmeasurable_metric_is_indeterminate_not_admitted(self):
        inventory = FakeInventory(result=ObservationResult(reason_code=CapacityReasonCode.MEASUREMENT_UNAVAILABLE))

        result = _assess(demand=1.0, inventory=inventory)

        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert result.blocking is False

    def test_unknown_partition_is_indeterminate_not_admitted(self):
        """An undeclared partition is a configuration gap, never free headroom."""
        result = _assess(partition="not-in-catalog")

        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert CapacityReservation.objects.count() == 0


class TestOverlappingReservations:
    """Committed reservations from other events consume headroom."""

    def test_overlapping_reservation_is_subtracted(self):
        _reserve(uuid4(), amount=95.0)

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.WARNING

    def test_released_reservation_is_not_counted(self):
        reservation = _reserve(uuid4(), amount=95.0)
        reservation.released_at = NOW
        reservation.save(update_fields=["released_at"])

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.ADMITTED

    def test_non_overlapping_window_is_not_counted(self):
        _reserve(uuid4(), amount=95.0, start=NOW + timedelta(days=2), end=NOW + timedelta(days=2, hours=4))

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.ADMITTED

    def test_reservation_in_another_partition_is_not_counted(self):
        """Cross-account partitioning is meaningless if reservations bleed across."""
        _reserve(uuid4(), amount=95.0, partition="aws-overflow-use2")

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.ADMITTED

    def test_reservation_for_another_metric_is_not_counted(self):
        _reserve(uuid4(), amount=95.0, metric="bedrock_tpm")

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.ADMITTED

    def test_partially_overlapping_window_is_counted(self):
        """Any overlap at all means the two events contend for the same capacity."""
        _reserve(uuid4(), amount=95.0, start=NOW + timedelta(hours=3), end=NOW + timedelta(hours=8))

        result = _assess(demand=10.0, inventory=FakeInventory(limit=100.0))

        assert result.outcome is CapacityOutcome.WARNING


class TestTransactionDiscipline:
    """Provider state cannot be locked, so reads stay out of the write transaction."""

    def test_provider_reads_happen_outside_the_reserving_transaction(self):
        """Moving the observe call inside the atomic block would push a savepoint."""
        inventory = FakeInventory()

        _assess(inventory=inventory)

        assert inventory.calls == 1
        assert inventory.savepoint_depth_at_call == [0]

    def test_no_capacity_is_reserved_before_the_provider_is_read(self):
        """Reserving first would let a failed read leave phantom commitments."""
        inventory = FakeInventory()

        _assess(inventory=inventory)

        assert inventory.reservations_at_call == [0]


class TestAssessmentRecord:
    """The persisted assessment is an immutable, pinned snapshot."""

    def test_assessment_is_persisted_with_policy_version_and_partition(self):
        catalog = _catalog()
        event_ref = uuid4()

        _assess(event_ref=event_ref, catalog=catalog)

        record = CapacityAssessment.objects.get(event_ref=event_ref)
        assert record.policy_version == catalog.policy_version
        assert record.partition_name == "aws-dev-use2"
        assert record.outcome == CapacityOutcome.ADMITTED.value

    def test_verdicts_are_stored_as_bounded_codes_without_raw_figures(self):
        event_ref = uuid4()

        _assess(event_ref=event_ref, demand=2_000_000.0, inventory=FakeInventory(limit=987654.0))

        record = CapacityAssessment.objects.get(event_ref=event_ref)
        serialized = str(record.verdicts)
        assert "987654" not in serialized
        assert CapacityReasonCode.EXCEEDS_HEADROOM.value in serialized

    def test_each_assessment_appends_rather_than_mutating(self):
        event_ref = uuid4()

        _assess(event_ref=event_ref)
        _assess(event_ref=event_ref)

        assert CapacityAssessment.objects.filter(event_ref=event_ref).count() == 2


class TestRelease:
    """Cancellation, cleanup, and retry release reservations idempotently."""

    def test_release_marks_open_reservations(self):
        event_ref = uuid4()
        _assess(event_ref=event_ref)

        released = release_capacity_reservations(event_ref, now=NOW)

        assert released == 1
        assert CapacityReservation.objects.filter(event_ref=event_ref, released_at__isnull=True).count() == 0

    def test_release_is_idempotent(self):
        event_ref = uuid4()
        _assess(event_ref=event_ref)

        release_capacity_reservations(event_ref, now=NOW)
        second = release_capacity_reservations(event_ref, now=NOW)

        assert second == 0

    def test_release_does_not_touch_other_events(self):
        keep = uuid4()
        _assess(event_ref=keep)
        _assess(event_ref=uuid4())

        release_capacity_reservations(uuid4(), now=NOW)

        assert CapacityReservation.objects.filter(released_at__isnull=True).count() == 2

    def test_released_capacity_becomes_available_again(self):
        holder = uuid4()
        _assess(event_ref=holder, demand=95.0)

        assert _assess(demand=10.0).outcome is CapacityOutcome.WARNING
        release_capacity_reservations(holder, now=NOW)
        assert _assess(demand=10.0).outcome is CapacityOutcome.ADMITTED
