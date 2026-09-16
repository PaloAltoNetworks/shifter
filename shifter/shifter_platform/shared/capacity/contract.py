"""Closed capacity-admission policy: does declared demand fit observed headroom (PLAT-201).

This is the Django-free policy seam shared by the Engine assessment service
(authoritative admission, before reservation and dispatch) and the cloud
capacity-inventory adapters that supply observations. It is intentionally
dependency-light -- stdlib only, inert on import -- so the standalone
provisioner and the portal both import it, exactly as they both import
``shared.range_instantiation_policy`` and ``shared.raes.realizability``.

Three rules carry the safety of the whole layer:

1. ``INDETERMINATE`` is not ``ADMITTED``. An unreadable, stale, or unsupported
   measurement proves nothing about current headroom, so it is never silently
   converted to zero usage or to sufficient room.
2. The least-permissive verdict wins. No metric that fits can upgrade a peer
   metric that does not, or one that could not be measured at all.
3. Verdicts carry bounded reason codes, never raw provider figures. Quota
   limits, usage readings, and account-level numbers stay inside
   :class:`MetricObservation`, which does not cross a product boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class CapacityOutcome(StrEnum):
    """Closed outcome of a capacity assessment.

    ``INDETERMINATE`` means the assessment could not be completed (no adapter,
    an unreachable provider, a reading past its freshness limit). It is
    deliberately distinct from ``REJECTED``: one is a proven shortfall, the
    other is an inability to prove anything. Neither may be rendered or
    admitted as available headroom.
    """

    ADMITTED = "admitted"
    WARNING = "warning"
    INDETERMINATE = "indeterminate"
    REJECTED = "rejected"


class EnforcementMode(StrEnum):
    """Whether an over-limit metric blocks the launch or only warns.

    ``ADVISORY`` is the default for every metric: an over-limit reading emits a
    visible operator warning and an audit record but provisioning proceeds, so a
    miscalibrated limit cannot block a live event. Operators promote individual
    metrics to ``ENFORCING`` once they trust the numbers.
    """

    ADVISORY = "advisory"
    ENFORCING = "enforcing"


class MeasurementSource(StrEnum):
    """Where a metric's observation comes from.

    The source is part of the metric's catalog entry rather than inferred, so an
    operator can tell a deployment-declared ceiling from a live provider reading
    when reading an assessment record.
    """

    CONFIG_LIMIT = "config_limit"
    PROVIDER_PROBE = "provider_probe"
    DB_RESERVATION = "db_reservation"


class CapacityReasonCode(StrEnum):
    """Bounded reason a metric reached its outcome.

    Clients -- API envelopes, operator notifications, audit rows -- switch on
    this code and never on prose. The set is closed so a new provider failure
    mode cannot leak an unbounded string onto a product surface.
    """

    AVAILABLE = "capacity.available"
    EXCEEDS_HEADROOM = "capacity.exceeds_headroom"
    MEASUREMENT_UNAVAILABLE = "capacity.measurement_unavailable"
    MEASUREMENT_STALE = "capacity.measurement_stale"
    METRIC_UNSUPPORTED = "capacity.metric_unsupported"


@dataclass(frozen=True, order=True)
class PartitionRef:
    """A deployment-owned target partition that capacity is assessed against.

    The identity tuple is what makes cross-account and cross-cloud partitioning
    meaningful: the same logical name in two accounts is two partitions, so a
    reservation in one never consumes headroom in the other. Partitions come
    from allowlisted deployment configuration -- never from an event name, a
    scenario, an organizer hint, or a mutable global provider setting.
    """

    name: str
    provider: str
    account: str
    region: str
    backend: str
    policy_profile: str = "default"


@dataclass(frozen=True)
class ProviderMetricRef:
    """Provider coordinates telling an adapter which reading to fetch.

    Deliberately opaque at this layer: the contract stays provider-neutral and
    each adapter parses its own reference format (AWS reads
    ``"<service-code>/<quota-code>"`` and ``"<namespace>/<metric-name>"``; GCP
    reads its own quota and metric-type identifiers). A metric with no
    ``ProviderMetricRef`` for the active backend is unsupported, which is an
    indeterminate answer -- never an assumption of available headroom.
    """

    limit_ref: str
    usage_ref: str = ""


@dataclass(frozen=True)
class ObservationResult:
    """An adapter's answer for one metric: a reading, or why there isn't one.

    Exactly one side is populated. ``reason_code`` is set only when
    ``observation`` is ``None``, and it distinguishes "no adapter mapping for
    this metric" from "we tried and could not read it" so operators can tell a
    configuration gap from an outage.
    """

    observation: MetricObservation | None = None
    reason_code: CapacityReasonCode | None = None


@dataclass(frozen=True)
class CapacityMetricSpec:
    """One catalog entry: what is measured, how, and how strictly.

    Shared-resource limits are not interchangeable -- Bedrock throughput, EC2
    vCPU, NAT bandwidth, and SSM concurrency have different units and
    observation models -- so every metric carries its own dimension, unit,
    freshness limit, safety margin, and enforcement mode rather than being
    lumped together as "quota".

    ``safety_margin_ratio`` is a fraction of the observed limit held back, which
    absorbs the race between an out-of-transaction provider read and the launch
    it admits. Provider state cannot be locked, so the margin and the freshness
    limit are what carry that risk.
    """

    name: str
    dimension: str
    unit: str
    partition: str
    source: MeasurementSource
    freshness_seconds: int
    safety_margin_ratio: float = 0.0
    enforcement: EnforcementMode = EnforcementMode.ADVISORY
    provider_ref: ProviderMetricRef | None = None
    #: Units of this metric one range consumes. Deployment-declared, because the
    #: answer depends on the instance types and provider the deployment chose.
    per_range_cost: float = 0.0
    #: Units one range *node* consumes, for metrics that scale with node count
    #: rather than with range count.
    per_node_cost: float = 0.0


@dataclass(frozen=True)
class MetricObservation:
    """One measurement of a metric in a partition.

    Holds the raw provider figures. This object is an *input* to policy and to
    operator-only projections; it is deliberately not embedded in
    :class:`MetricVerdict`, so a quota limit or account-level usage reading
    cannot ride a verdict onto an organizer-facing surface.
    """

    limit: float
    usage: float
    observed_at: datetime
    source: MeasurementSource
    reserved: float = 0.0

    def available(self, safety_margin_ratio: float = 0.0) -> float:
        """Return capacity available for new demand.

        Observed limit less observed usage, less capacity already committed to
        overlapping reservations, less the configured safety margin.
        """
        return self.limit - self.usage - self.reserved - (self.limit * safety_margin_ratio)

    def is_stale(self, *, now: datetime, freshness_seconds: int) -> bool:
        """Return whether this reading is older than its metric's freshness limit."""
        return (now - self.observed_at).total_seconds() > freshness_seconds


@dataclass(frozen=True)
class MetricVerdict:
    """The safe, boundary-crossing answer for one metric.

    Carries the stable ``reason_code``, the outcome, the enforcement mode that
    produced it, and when the underlying reading was taken -- never the limit,
    the usage, the account, or any provider payload.
    """

    metric_name: str
    outcome: CapacityOutcome
    reason_code: CapacityReasonCode
    enforcement: EnforcementMode
    observed_at: datetime | None


@dataclass(frozen=True)
class CapacityAssessmentResult:
    """The folded answer for one partition at one point in time.

    Immutable and pinned to the policy version and observation time so a later
    retry, destroy, or reconciliation reads the decision that was actually made
    rather than re-deriving it against drifted configuration.
    """

    partition: PartitionRef
    policy_version: str
    observed_at: datetime
    verdicts: tuple[MetricVerdict, ...] = field(default_factory=tuple)

    @property
    def outcome(self) -> CapacityOutcome:
        """Least-permissive outcome across every metric verdict."""
        return worst_outcome(verdict.outcome for verdict in self.verdicts)

    @property
    def measured(self) -> bool:
        """Whether any metric actually produced a verdict.

        ``worst_outcome(())`` is ``ADMITTED``, which is right for "every metric
        fit" and wrong for "no metric was ever assessed". Callers that build a
        result from a possibly-empty verdict set check this before treating
        ``outcome`` as an answer.
        """
        return bool(self.verdicts)

    @property
    def blocking(self) -> bool:
        """Whether this assessment must stop the launch.

        Only a ``REJECTED`` outcome blocks. A warning is the advisory path
        working as intended, and an indeterminate reading warns operators
        without refusing every event whose metric happens to be unmeasurable.
        """
        return self.outcome is CapacityOutcome.REJECTED


def worst_outcome(outcomes: Iterable[CapacityOutcome]) -> CapacityOutcome:
    """Combine metric outcomes, keeping the least-permissive one.

    ``REJECTED`` beats ``INDETERMINATE`` beats ``WARNING`` beats ``ADMITTED``,
    so neither a proven shortfall nor an inability to measure can be masked by
    metrics that fit.
    """
    ranked = list(outcomes)
    for candidate in (
        CapacityOutcome.REJECTED,
        CapacityOutcome.INDETERMINATE,
        CapacityOutcome.WARNING,
    ):
        if candidate in ranked:
            return candidate
    return CapacityOutcome.ADMITTED


def evaluate_metric(
    spec: CapacityMetricSpec,
    *,
    demand: float,
    observation: MetricObservation | None,
    now: datetime,
) -> MetricVerdict:
    """Assess one metric's demand against its observation.

    A missing or stale observation yields ``INDETERMINATE`` -- never ``ADMITTED``
    and never a fabricated zero-usage reading. An over-limit metric warns under
    an advisory policy and rejects under an enforcing one; it never silently
    proceeds.
    """
    if observation is None:
        return _indeterminate(spec, CapacityReasonCode.MEASUREMENT_UNAVAILABLE, observed_at=None)
    if observation.is_stale(now=now, freshness_seconds=spec.freshness_seconds):
        return _indeterminate(spec, CapacityReasonCode.MEASUREMENT_STALE, observed_at=observation.observed_at)

    if demand <= observation.available(spec.safety_margin_ratio):
        outcome = CapacityOutcome.ADMITTED
        reason_code = CapacityReasonCode.AVAILABLE
    else:
        outcome = CapacityOutcome.REJECTED if spec.enforcement is EnforcementMode.ENFORCING else CapacityOutcome.WARNING
        reason_code = CapacityReasonCode.EXCEEDS_HEADROOM

    return MetricVerdict(
        metric_name=spec.name,
        outcome=outcome,
        reason_code=reason_code,
        enforcement=spec.enforcement,
        observed_at=observation.observed_at,
    )


def _indeterminate(
    spec: CapacityMetricSpec,
    reason_code: CapacityReasonCode,
    *,
    observed_at: datetime | None,
) -> MetricVerdict:
    """Build the verdict for a metric that could not be assessed."""
    return MetricVerdict(
        metric_name=spec.name,
        outcome=CapacityOutcome.INDETERMINATE,
        reason_code=reason_code,
        enforcement=spec.enforcement,
        observed_at=observed_at,
    )


@runtime_checkable
class CapacityInventoryPort(Protocol):
    """The read-only observation seam capacity policy depends on.

    Declared here rather than in ``shared.cloud`` so the Engine can name the
    dependency it actually has without importing a provider package, and so a
    test double is a first-class implementation rather than an untyped stand-in.
    """

    def observe(self, spec: CapacityMetricSpec, partition: PartitionRef) -> ObservationResult: ...
