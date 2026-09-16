"""Pure capacity-admission contract semantics (PLAT-201, #680).

These exercise the Django-free policy core: outcome precedence, headroom
arithmetic, enforcement modes, and the indeterminate rules. No database, no
provider clients -- the contract is stdlib-only by design so the provisioner
and the portal can both import it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared.capacity import (
    CapacityAssessmentResult,
    CapacityMetricSpec,
    CapacityOutcome,
    CapacityReasonCode,
    EnforcementMode,
    MeasurementSource,
    MetricObservation,
    MetricVerdict,
    PartitionRef,
    evaluate_metric,
    worst_outcome,
)

OBSERVED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _partition(name: str = "aws-dev-use2") -> PartitionRef:
    return PartitionRef(
        name=name,
        provider="aws",
        account="111122223333",
        region="us-east-2",
        backend="ecs",
        policy_profile="default",
    )


def _spec(**overrides: object) -> CapacityMetricSpec:
    defaults: dict[str, object] = {
        "name": "ec2_vcpu",
        "dimension": "vcpu",
        "unit": "count",
        "partition": "aws-dev-use2",
        "source": MeasurementSource.PROVIDER_PROBE,
        "freshness_seconds": 300,
        "safety_margin_ratio": 0.0,
        "enforcement": EnforcementMode.ADVISORY,
    }
    defaults.update(overrides)
    return CapacityMetricSpec(**defaults)  # type: ignore[arg-type]


def _observation(**overrides: object) -> MetricObservation:
    defaults: dict[str, object] = {
        "limit": 100.0,
        "usage": 0.0,
        "reserved": 0.0,
        "observed_at": OBSERVED_AT,
        "source": MeasurementSource.PROVIDER_PROBE,
    }
    defaults.update(overrides)
    return MetricObservation(**defaults)  # type: ignore[arg-type]


class TestWorstOutcome:
    """Least-permissive outcome wins; no contributor upgrades another's answer."""

    @pytest.mark.parametrize(
        ("outcomes", "expected"),
        [
            ((), CapacityOutcome.ADMITTED),
            ((CapacityOutcome.ADMITTED,), CapacityOutcome.ADMITTED),
            ((CapacityOutcome.ADMITTED, CapacityOutcome.WARNING), CapacityOutcome.WARNING),
            (
                (CapacityOutcome.ADMITTED, CapacityOutcome.WARNING, CapacityOutcome.INDETERMINATE),
                CapacityOutcome.INDETERMINATE,
            ),
            (
                (CapacityOutcome.INDETERMINATE, CapacityOutcome.REJECTED),
                CapacityOutcome.REJECTED,
            ),
            (
                (CapacityOutcome.REJECTED, CapacityOutcome.ADMITTED, CapacityOutcome.WARNING),
                CapacityOutcome.REJECTED,
            ),
        ],
    )
    def test_precedence(self, outcomes, expected):
        assert worst_outcome(outcomes) == expected

    def test_indeterminate_is_never_upgraded_by_admitted_peers(self):
        """An inability to measure must not be masked by metrics that passed."""
        outcomes = [CapacityOutcome.ADMITTED] * 10 + [CapacityOutcome.INDETERMINATE]
        assert worst_outcome(outcomes) is CapacityOutcome.INDETERMINATE


class TestHeadroomArithmetic:
    """available = limit - usage - reserved - (limit * safety_margin_ratio)."""

    def test_demand_within_headroom_is_admitted(self):
        verdict = evaluate_metric(_spec(), demand=40.0, observation=_observation(usage=50.0), now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.ADMITTED
        assert verdict.reason_code is CapacityReasonCode.AVAILABLE

    def test_committed_reservations_consume_headroom(self):
        """Overlapping event reservations are subtracted, not ignored."""
        observation = _observation(usage=50.0, reserved=30.0)

        assert evaluate_metric(_spec(), demand=20.0, observation=observation, now=OBSERVED_AT).outcome is (
            CapacityOutcome.ADMITTED
        )
        # The same demand no longer fits once one more range-worth is reserved.
        assert evaluate_metric(_spec(), demand=21.0, observation=observation, now=OBSERVED_AT).outcome is (
            CapacityOutcome.WARNING
        )

    def test_safety_margin_reduces_available_capacity(self):
        """A 20% margin on a 100-unit limit leaves 80 usable."""
        spec = _spec(safety_margin_ratio=0.2)

        assert evaluate_metric(spec, demand=80.0, observation=_observation(), now=OBSERVED_AT).outcome is (
            CapacityOutcome.ADMITTED
        )
        assert evaluate_metric(spec, demand=81.0, observation=_observation(), now=OBSERVED_AT).outcome is (
            CapacityOutcome.WARNING
        )

    def test_exact_fit_is_admitted(self):
        verdict = evaluate_metric(_spec(), demand=100.0, observation=_observation(), now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.ADMITTED


class TestEnforcementModes:
    """Advisory warns and proceeds; enforcing rejects. Neither ever silently passes."""

    def test_advisory_over_limit_warns(self):
        verdict = evaluate_metric(
            _spec(enforcement=EnforcementMode.ADVISORY),
            demand=200.0,
            observation=_observation(),
            now=OBSERVED_AT,
        )

        assert verdict.outcome is CapacityOutcome.WARNING
        assert verdict.reason_code is CapacityReasonCode.EXCEEDS_HEADROOM

    def test_enforcing_over_limit_rejects(self):
        verdict = evaluate_metric(
            _spec(enforcement=EnforcementMode.ENFORCING),
            demand=200.0,
            observation=_observation(),
            now=OBSERVED_AT,
        )

        assert verdict.outcome is CapacityOutcome.REJECTED
        assert verdict.reason_code is CapacityReasonCode.EXCEEDS_HEADROOM

    def test_advisory_is_the_default_enforcement_mode(self):
        """First ship defaults to warn so a miscalibrated limit cannot block an event."""
        spec = CapacityMetricSpec(
            name="bedrock_tpm",
            dimension="tokens_per_minute",
            unit="tokens/min",
            partition="aws-dev-use2",
            source=MeasurementSource.PROVIDER_PROBE,
            freshness_seconds=300,
        )

        assert spec.enforcement is EnforcementMode.ADVISORY


class TestIndeterminateRules:
    """Unmeasurable is never silently converted to sufficient headroom."""

    def test_missing_observation_is_indeterminate(self):
        verdict = evaluate_metric(_spec(), demand=1.0, observation=None, now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.INDETERMINATE
        assert verdict.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_stale_observation_is_indeterminate_not_admitted(self):
        """A reading older than the freshness limit proves nothing about now."""
        stale = _observation(observed_at=OBSERVED_AT - timedelta(seconds=301))

        verdict = evaluate_metric(_spec(freshness_seconds=300), demand=1.0, observation=stale, now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.INDETERMINATE
        assert verdict.reason_code is CapacityReasonCode.MEASUREMENT_STALE

    def test_observation_inside_freshness_window_is_used(self):
        fresh = _observation(observed_at=OBSERVED_AT - timedelta(seconds=299))

        verdict = evaluate_metric(_spec(freshness_seconds=300), demand=1.0, observation=fresh, now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.ADMITTED

    def test_unsupported_metric_is_indeterminate_even_when_demand_is_zero(self):
        """No adapter for the metric means no answer -- not 'plenty of room'."""
        verdict = evaluate_metric(
            _spec(source=MeasurementSource.PROVIDER_PROBE),
            demand=0.0,
            observation=None,
            now=OBSERVED_AT,
        )

        assert verdict.outcome is not CapacityOutcome.ADMITTED

    def test_negative_available_capacity_never_reads_as_headroom(self):
        """Usage already past the limit yields no room, not a negative that passes."""
        verdict = evaluate_metric(_spec(), demand=1.0, observation=_observation(usage=150.0), now=OBSERVED_AT)

        assert verdict.outcome is CapacityOutcome.WARNING


class TestSafeProjection:
    """Verdicts crossing a boundary carry bounded codes, never raw provider figures."""

    def test_verdict_carries_no_raw_provider_numbers(self):
        observation = _observation(limit=987654.0, usage=123456.0)
        verdict = evaluate_metric(_spec(), demand=2_000_000.0, observation=observation, now=OBSERVED_AT)

        rendered = repr(verdict)
        assert "987654" not in rendered
        assert "123456" not in rendered
        assert verdict.reason_code is CapacityReasonCode.EXCEEDS_HEADROOM

    def test_reason_codes_are_a_closed_stable_set(self):
        """Clients switch on the code, never on prose."""
        assert {code.value for code in CapacityReasonCode} == {
            "capacity.available",
            "capacity.exceeds_headroom",
            "capacity.measurement_unavailable",
            "capacity.measurement_stale",
            "capacity.metric_unsupported",
        }


class TestAssessmentResult:
    """The result's outcome is the least-permissive of its verdicts."""

    def _verdict(self, outcome: CapacityOutcome, name: str) -> MetricVerdict:
        return MetricVerdict(
            metric_name=name,
            outcome=outcome,
            reason_code=CapacityReasonCode.AVAILABLE,
            enforcement=EnforcementMode.ADVISORY,
            observed_at=OBSERVED_AT,
        )

    def test_result_outcome_folds_verdicts(self):
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(
                self._verdict(CapacityOutcome.ADMITTED, "a"),
                self._verdict(CapacityOutcome.WARNING, "b"),
            ),
        )

        assert result.outcome is CapacityOutcome.WARNING

    def test_result_is_admitted_only_when_every_verdict_is(self):
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(
                self._verdict(CapacityOutcome.ADMITTED, "a"),
                self._verdict(CapacityOutcome.ADMITTED, "b"),
            ),
        )

        assert result.outcome is CapacityOutcome.ADMITTED
        assert result.blocking is False

    def test_rejected_result_is_blocking(self):
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(self._verdict(CapacityOutcome.REJECTED, "a"),),
        )

        assert result.blocking is True

    def test_warning_result_is_not_blocking(self):
        """Advisory is the whole point: a warning must not stop the spinup."""
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(self._verdict(CapacityOutcome.WARNING, "a"),),
        )

        assert result.blocking is False

    def test_indeterminate_result_is_not_blocking_but_is_visible(self):
        """Cannot-measure warns operators without refusing every event by default."""
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(self._verdict(CapacityOutcome.INDETERMINATE, "a"),),
        )

        assert result.blocking is False
        assert result.outcome is CapacityOutcome.INDETERMINATE


class TestPartitionRef:
    """Partitions are deployment-owned identities, hashable and comparable."""

    def test_partition_is_frozen_and_hashable(self):
        partition = _partition()

        assert {partition, _partition()} == {partition}
        with pytest.raises((AttributeError, TypeError)):
            partition.region = "us-west-2"  # type: ignore[misc]

    def test_partitions_with_different_accounts_are_distinct(self):
        """Cross-account partitioning depends on the account being part of identity."""
        other = PartitionRef(
            name="aws-dev-use2",
            provider="aws",
            account="123456789012",
            region="us-east-2",
            backend="ecs",
            policy_profile="default",
        )

        assert other != _partition()


class TestEmptyVerdictSafety:
    """An assessment that produced no verdicts must not read as admitted.

    ``worst_outcome(())`` is ADMITTED, which is correct for "every metric
    passed" but dangerous for "we never got a verdict". The result object
    distinguishes the two so an unassessable event cannot look like a fitting
    one (regression guard for the undeclared-partition path).
    """

    def test_result_with_no_verdicts_is_not_treated_as_measured(self):
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(),
        )

        assert result.measured is False

    def test_result_with_verdicts_is_measured(self):
        result = CapacityAssessmentResult(
            partition=_partition(),
            policy_version="v1",
            observed_at=OBSERVED_AT,
            verdicts=(
                MetricVerdict(
                    metric_name="ec2_vcpu",
                    outcome=CapacityOutcome.ADMITTED,
                    reason_code=CapacityReasonCode.AVAILABLE,
                    enforcement=EnforcementMode.ADVISORY,
                    observed_at=OBSERVED_AT,
                ),
            ),
        )

        assert result.measured is True
