"""Degraded and guard paths in capacity assessment (PLAT-201, #680).

The happy path is covered by ``test_capacity_plan``. These drive the paths that
only run when something has gone wrong, which is exactly where a capacity layer
is most dangerous: every one of them must degrade to "we could not measure this"
rather than to "there is room".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from engine.models import CapacityDeclaration, CapacityReservation
from engine.services._capacity_plan import (
    _demand_from_declaration,
    _NullInventory,
    _observe,
    _resolve_window,
    assess_declared_event_capacity,
)
from shared.capacity import CapacityOutcome, CapacityReasonCode, PartitionRef
from shared.capacity.catalog import load_catalog

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)

CATALOG = load_catalog(
    {
        "partitions": [
            {
                "name": "p",
                "provider": "aws",
                "account": "111122223333",
                "region": "us-east-2",
                "backend": "ecs",
            }
        ],
        "metrics": [
            {
                "name": "ec2_vcpu",
                "dimension": "vcpu",
                "unit": "count",
                "partition": "p",
                "source": "provider_probe",
                "freshness_seconds": 900,
                "per_range_cost": 2,
            }
        ],
    }
)

PARTITION = PartitionRef(
    name="p",
    provider="aws",
    account="111122223333",
    region="us-east-2",
    backend="ecs",
)


class TestObserveGuards:
    def test_missing_spec_is_unmeasured(self):
        assert _observe(_NullInventory(), None, PARTITION) is None

    def test_raising_adapter_degrades_instead_of_propagating(self):
        """Adapters are contractually non-raising; this is the backstop."""

        class Exploding:
            def observe(self, spec, partition):
                raise RuntimeError("boom")

        spec = CATALOG.metrics_for("p")[0]

        assert _observe(Exploding(), spec, PARTITION) is None

    def test_null_inventory_reports_unsupported(self):
        spec = CATALOG.metrics_for("p")[0]

        result = _NullInventory.observe(spec, PARTITION)

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.METRIC_UNSUPPORTED


class TestWindowResolution:
    def test_absent_window_gets_a_default_horizon(self):
        start, end = _resolve_window(None, None, NOW)

        assert start == NOW
        assert end > start

    def test_inverted_window_is_corrected(self):
        """An end at or before the start would make every overlap query empty."""
        start, end = _resolve_window(NOW, NOW - timedelta(hours=1), NOW)

        assert end > start

    def test_declared_window_is_preserved(self):
        finish = NOW + timedelta(hours=3)

        assert _resolve_window(NOW, finish, NOW) == (NOW, finish)


class TestDemandFromDeclaration:
    def test_agent_mix_drives_node_count(self):
        declaration = CapacityDeclaration(
            event_ref=uuid4(),
            expected_concurrent_ranges=4,
            cohort_size=4,
            resource_hints={"agents_by_os": {"windows": 2, "linux": 1}},
        )

        demand = _demand_from_declaration(declaration, CATALOG, "p")

        assert demand.amounts["ec2_vcpu"] == pytest.approx(8.0)

    def test_malformed_agent_mix_is_ignored_not_trusted(self):
        """capacity_hints is organizer JSON and is never authoritative."""
        declaration = CapacityDeclaration(
            event_ref=uuid4(),
            expected_concurrent_ranges=2,
            cohort_size=2,
            resource_hints={"agents_by_os": {"windows": -5, "linux": "many", "mac": True}},
        )

        demand = _demand_from_declaration(declaration, CATALOG, "p")

        assert demand.image_counts == ()

    def test_non_dict_hints_do_not_raise(self):
        declaration = CapacityDeclaration(
            event_ref=uuid4(),
            expected_concurrent_ranges=1,
            cohort_size=1,
            resource_hints=[],
        )

        assert _demand_from_declaration(declaration, CATALOG, "p").partition_name == "p"


class TestDeclaredAssessmentGuards:
    def test_disabled_layer_returns_no_opinion(self, settings):
        settings.CAPACITY_PLANNING_ENABLED = False

        assert assess_declared_event_capacity(uuid4()) is None

    def test_event_without_a_declaration_returns_no_opinion(self, settings):
        settings.CAPACITY_PLANNING_ENABLED = True

        assert assess_declared_event_capacity(uuid4()) is None

    def test_undeclared_partition_is_indeterminate_and_reserves_nothing(self, settings):
        settings.CAPACITY_PLANNING_ENABLED = True
        settings.CAPACITY_PLANNING_CATALOG = CATALOG
        settings.CAPACITY_PLANNING_DEFAULT_PARTITION = "not-declared"
        event_ref = uuid4()
        CapacityDeclaration.objects.create(
            event_ref=event_ref,
            expected_concurrent_ranges=3,
            cohort_size=3,
            resource_hints={},
        )

        result = assess_declared_event_capacity(event_ref, inventory=_NullInventory(), now=NOW)

        assert result is not None
        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert CapacityReservation.objects.count() == 0

    def test_unsupported_metric_yields_indeterminate_without_reserving_nonsense(self, settings):
        settings.CAPACITY_PLANNING_ENABLED = True
        settings.CAPACITY_PLANNING_CATALOG = CATALOG
        settings.CAPACITY_PLANNING_DEFAULT_PARTITION = "p"
        event_ref = uuid4()
        CapacityDeclaration.objects.create(
            event_ref=event_ref,
            expected_concurrent_ranges=3,
            cohort_size=3,
            resource_hints={},
        )

        result = assess_declared_event_capacity(event_ref, inventory=_NullInventory(), now=NOW)

        assert result is not None
        assert result.outcome is CapacityOutcome.INDETERMINATE
