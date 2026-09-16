"""CTF-side capacity helper behaviour (PLAT-201, #680).

These cover the degraded paths the wiring depends on: a capacity problem must
never be the reason a range fails to provision, and every summary that crosses
to an organizer surface carries bounded codes only.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from ctf.services.range.capacity import (
    _project_images,
    admit_range,
    assess_declared_capacity,
    release_range,
)
from shared.capacity import (
    CapacityAssessmentResult,
    CapacityOutcome,
    CapacityReasonCode,
    EnforcementMode,
    MetricVerdict,
    PartitionRef,
)

pytestmark = pytest.mark.django_db


def _result(outcome: CapacityOutcome, reason: CapacityReasonCode) -> CapacityAssessmentResult:
    return CapacityAssessmentResult(
        partition=PartitionRef(
            name="aws-dev-use2",
            provider="aws",
            account="111122223333",
            region="us-east-2",
            backend="ecs",
        ),
        policy_version="v1",
        observed_at=None,  # type: ignore[arg-type]
        verdicts=(
            MetricVerdict(
                metric_name="ec2_vcpu",
                outcome=outcome,
                reason_code=reason,
                enforcement=EnforcementMode.ADVISORY,
                observed_at=None,
            ),
        ),
    )


class TestAssessSummary:
    def test_summary_projects_outcome_and_codes(self, monkeypatch):
        monkeypatch.setattr(
            "ctf.bridges.cms_assess_event_capacity",
            lambda event_ref: _result(CapacityOutcome.WARNING, CapacityReasonCode.EXCEEDS_HEADROOM),
        )

        summary = assess_declared_capacity(uuid4(), source="test")

        assert summary is not None
        assert summary["outcome"] == "warning"
        assert summary["blocking"] is False
        assert summary["reason_codes"] == ["capacity.exceeds_headroom"]

    def test_no_result_means_no_opinion(self, monkeypatch):
        monkeypatch.setattr("ctf.bridges.cms_assess_event_capacity", lambda event_ref: None)

        assert assess_declared_capacity(uuid4(), source="test") is None

    def test_bridge_failure_is_swallowed(self, monkeypatch):
        def _boom(event_ref):
            raise RuntimeError("engine down")

        monkeypatch.setattr("ctf.bridges.cms_assess_event_capacity", _boom)

        assert assess_declared_capacity(uuid4(), source="test") is None

    def test_rejected_summary_is_blocking(self, monkeypatch):
        monkeypatch.setattr(
            "ctf.bridges.cms_assess_event_capacity",
            lambda event_ref: _result(CapacityOutcome.REJECTED, CapacityReasonCode.EXCEEDS_HEADROOM),
        )

        summary = assess_declared_capacity(uuid4(), source="test")

        assert summary is not None
        assert summary["blocking"] is True


class TestAdmitSummary:
    def test_summary_projects_outcome(self, monkeypatch):
        monkeypatch.setattr(
            "ctf.bridges.cms_admit_range_capacity",
            lambda event_ref, draw_key: _result(CapacityOutcome.ADMITTED, CapacityReasonCode.AVAILABLE),
        )

        summary = admit_range(uuid4(), uuid4())

        assert summary is not None
        assert summary["outcome"] == "admitted"
        assert summary["blocking"] is False

    def test_admit_summary_carries_no_partition_topology(self, monkeypatch):
        """The per-range summary reaches product paths; keep topology out of it."""
        monkeypatch.setattr(
            "ctf.bridges.cms_admit_range_capacity",
            lambda event_ref, draw_key: _result(CapacityOutcome.ADMITTED, CapacityReasonCode.AVAILABLE),
        )

        summary = admit_range(uuid4(), uuid4())

        assert summary is not None
        assert "partition" not in summary

    def test_bridge_failure_is_swallowed(self, monkeypatch):
        def _boom(event_ref, draw_key):
            raise RuntimeError("engine down")

        monkeypatch.setattr("ctf.bridges.cms_admit_range_capacity", _boom)

        assert admit_range(uuid4(), uuid4()) is None

    def test_none_result_is_no_opinion(self, monkeypatch):
        monkeypatch.setattr("ctf.bridges.cms_admit_range_capacity", lambda event_ref, draw_key: None)

        assert admit_range(uuid4(), uuid4()) is None


class TestRelease:
    def test_release_delegates(self, monkeypatch):
        seen = []
        monkeypatch.setattr("ctf.bridges.cms_release_range_capacity", lambda draw_key: seen.append(draw_key))
        key = uuid4()

        release_range(key)

        assert seen == [key]

    def test_release_failure_is_swallowed(self, monkeypatch):
        """Teardown must not fail because the ledger could not be updated."""

        def _boom(draw_key):
            raise RuntimeError("engine down")

        monkeypatch.setattr("ctf.bridges.cms_release_range_capacity", _boom)

        release_range(uuid4())


class TestImageProjectionHelper:
    def test_projection_is_passed_through(self, monkeypatch):
        payload = {"resolved": True, "per_range": [], "shared": []}
        monkeypatch.setattr("ctf.bridges.cms_project_scenario_images", lambda scenario_id: payload)

        assert _project_images("basic") == payload

    def test_projection_failure_yields_unresolved(self, monkeypatch):
        """An unreadable scenario must not look like a scenario needing no images."""

        def _boom(scenario_id):
            raise RuntimeError("registry down")

        monkeypatch.setattr("ctf.bridges.cms_project_scenario_images", _boom)

        assert _project_images("basic") == {"resolved": False, "per_range": [], "shared": []}
