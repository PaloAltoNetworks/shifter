"""Range-escape validation runner (issue #1347).

Given a range under test (and optional peers), the platform network inventory,
the egress policy, and a probe-launch adapter, the runner launches the bounded
probes from participant context, classifies each observation into a
:class:`shared.range_escape.CheckResult`, and assembles the closed
:class:`shared.range_escape.EscapeReport`. One-range and multi-range runs use the
same contract; the multi-range run adds a peer as a negative target for
cross-range and management-ingress boundaries and records peer-dependent
boundaries as ``not_applicable`` when no peer is supplied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from cms.range_escape.inventory import build_management_ingress_targets, build_subject_targets
from cms.range_escape.model import (
    EgressPolicy,
    ObservedProbe,
    ParticipantContext,
    PlatformInventory,
    ProbeOutcome,
    ProbeTarget,
    RangeUnderTest,
)
from shared.range_escape import (
    PEER_DEPENDENT_BOUNDARIES,
    REQUIRED_CORE_BOUNDARIES,
    BoundaryCode,
    CheckContext,
    CheckResult,
    CheckScope,
    CheckStatus,
    DestinationClass,
    EscapeReport,
    Outcome,
    SuiteMode,
    evaluate_check,
    sanitize_diagnostic,
)

_DEFAULT_PER_TARGET_TIMEOUT_S = 4

_DESTINATION_BY_BOUNDARY: dict[BoundaryCode, DestinationClass] = {
    BoundaryCode.CROSS_RANGE_PRIVATE_IP: DestinationClass.PEER_RANGE,
    BoundaryCode.CROSS_RANGE_DNS: DestinationClass.PEER_RANGE,
    BoundaryCode.PLATFORM_POD_CIDR: DestinationClass.PLATFORM_POD,
    BoundaryCode.PLATFORM_SERVICE_CIDR: DestinationClass.PLATFORM_SERVICE,
    BoundaryCode.PLATFORM_NODE_IP: DestinationClass.PLATFORM_NODE,
    BoundaryCode.PLATFORM_PORTAL_PRIVATE: DestinationClass.PORTAL_PRIVATE,
    BoundaryCode.GKE_GDC_API: DestinationClass.GKE_GDC_API,
    BoundaryCode.METADATA_SERVER: DestinationClass.METADATA,
    BoundaryCode.INTERNET_EGRESS: DestinationClass.INTERNET,
    BoundaryCode.MANAGEMENT_INGRESS: DestinationClass.MANAGEMENT,
}


class ProbeLauncher(Protocol):
    """Launches the bounded probe in a range's participant context (the seam adapters implement)."""

    def launch(
        self, participant: ParticipantContext, targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = ...
    ) -> dict[str, ObservedProbe]: ...


@dataclass(frozen=True)
class RunOptions:
    """Suite identity, timing, policy fingerprints, and the per-probe timeout for a run."""

    suite_id: str
    started_at: str
    ended_at: str
    policy_inputs: dict[str, str] = field(default_factory=dict)
    per_target_timeout_s: int = _DEFAULT_PER_TARGET_TIMEOUT_S


def run_escape_validation(
    *,
    subject: RangeUnderTest,
    platform: PlatformInventory,
    egress: EgressPolicy,
    launcher: ProbeLauncher,
    options: RunOptions,
    peers: Sequence[RangeUnderTest] = (),
) -> EscapeReport:
    """Run the escape suite against ``subject`` (and ``peers``) and return the report."""
    mode = SuiteMode.MULTI_RANGE if peers else SuiteMode.ONE_RANGE
    timeout = options.per_target_timeout_s
    checks: list[CheckResult] = []

    subject_source = _source_label(subject.range_id)
    subject_targets = build_subject_targets(subject=subject, peers=peers, platform=platform, egress=egress)
    subject_obs = launcher.launch(subject.participant, subject_targets, per_target_timeout_s=timeout)
    checks.extend(_result_for(target, subject_obs.get(target.check_id), subject_source) for target in subject_targets)

    for peer in peers:
        peer_source = _source_label(peer.range_id)
        mgmt_targets = build_management_ingress_targets(subject=subject, peer=peer)
        peer_obs = launcher.launch(peer.participant, mgmt_targets, per_target_timeout_s=timeout)
        checks.extend(_result_for(target, peer_obs.get(target.check_id), peer_source) for target in mgmt_targets)

    checks.extend(_coverage_checks(checks, mode, subject_source))

    return EscapeReport(
        suite_id=options.suite_id,
        mode=mode,
        request_id=subject.request_id,
        range_id=subject.range_id,
        started_at=options.started_at,
        ended_at=options.ended_at,
        checks=checks,
        policy_inputs=dict(options.policy_inputs),
        peer_request_ids=[peer.request_id for peer in peers],
        peer_range_ids=[peer.range_id for peer in peers],
    )


def _result_for(target: ProbeTarget, observed: ObservedProbe | None, source_context: str) -> CheckResult:
    """Classify one probe observation into a check result (fail-closed if missing)."""
    if observed is None:
        return CheckResult(
            check_id=target.check_id,
            boundary_code=target.boundary_code,
            scope=CheckScope.CORE,
            source_context=source_context,
            destination_class=target.destination_class,
            expected=target.expected,
            observed=None,
            status=CheckStatus.FAIL,
            elapsed_ms=0,
            diagnostic="probe returned no observation",
        )
    if target.boundary_code == BoundaryCode.METADATA_SERVER:
        return _metadata_result(target, observed, source_context)
    status, observed_outcome = _status_for(target.expected, observed.outcome)
    return evaluate_check(
        _context(target, source_context),
        expected=target.expected,
        observed=observed_outcome,
        status=status,
        elapsed_ms=0,
        diagnostic=observed.detail,
    )


def _context(target: ProbeTarget, source_context: str) -> CheckContext:
    """Build the core check identity for a probe target."""
    return CheckContext(
        check_id=target.check_id,
        boundary_code=target.boundary_code,
        scope=CheckScope.CORE,
        source_context=source_context,
        destination_class=target.destination_class,
    )


def _status_for(expected: Outcome, outcome: ProbeOutcome) -> tuple[CheckStatus, Outcome | None]:
    """Map a probe outcome to a check status against the expected outcome.

    An ``error`` (capability/execution failure) is inconclusive and always fails
    closed. For an expected-unreachable boundary only a ``blocked`` (silent drop)
    outcome passes; ``refused`` means the network path reached the target host and
    ``reachable`` means a connection succeeded, so both fail. For an
    expected-reachable target (approved egress) only ``reachable`` passes.
    """
    if outcome == ProbeOutcome.ERROR:
        return CheckStatus.FAIL, None
    if expected == Outcome.UNREACHABLE:
        return (
            (CheckStatus.PASS, Outcome.UNREACHABLE)
            if outcome == ProbeOutcome.BLOCKED
            else (CheckStatus.FAIL, Outcome.REACHABLE)
        )
    return (
        (CheckStatus.PASS, Outcome.REACHABLE)
        if outcome == ProbeOutcome.REACHABLE
        else (CheckStatus.FAIL, Outcome.UNREACHABLE)
    )


def _metadata_result(target: ProbeTarget, observed: ObservedProbe, source_context: str) -> CheckResult:
    """Classify the metadata probe.

    Metadata is a failure only when it is reachable AND exposes useful credentials.
    Blocked/refused (not usefully reachable) pass; an error (capability failure) is
    inconclusive and fails closed.
    """
    if observed.outcome == ProbeOutcome.ERROR:
        status: CheckStatus = CheckStatus.FAIL
        observed_outcome: Outcome | None = None
    elif observed.outcome == ProbeOutcome.REACHABLE:
        useful = bool(observed.metadata_credentials_useful)
        status = CheckStatus.FAIL if useful else CheckStatus.PASS
        observed_outcome = Outcome.REACHABLE
    else:
        status = CheckStatus.PASS
        observed_outcome = Outcome.UNREACHABLE
    return evaluate_check(
        _context(target, source_context),
        expected=Outcome.UNREACHABLE,
        observed=observed_outcome,
        status=status,
        elapsed_ms=0,
        diagnostic=observed.detail,
    )


def _coverage_checks(existing: Sequence[CheckResult], mode: SuiteMode, source_context: str) -> list[CheckResult]:
    """Add explicit skip / not-applicable checks so every required boundary is represented."""
    covered = {check.boundary_code for check in existing}
    extra: list[CheckResult] = []
    for code in sorted(REQUIRED_CORE_BOUNDARIES, key=lambda c: c.value):
        if code not in covered:
            extra.append(_skip_check(code, CheckStatus.SKIP, "no target configured for this boundary", source_context))
    for code in sorted(PEER_DEPENDENT_BOUNDARIES, key=lambda c: c.value):
        if code not in covered:
            if mode == SuiteMode.ONE_RANGE:
                extra.append(_skip_check(code, CheckStatus.NOT_APPLICABLE, "no peer range supplied", source_context))
            else:
                extra.append(_skip_check(code, CheckStatus.SKIP, "no peer target resolved", source_context))
    return extra


def _skip_check(code: BoundaryCode, status: CheckStatus, reason: str, source_context: str) -> CheckResult:
    """Build an explicit skip / not-applicable check for an unprobed boundary."""
    return CheckResult(
        check_id=f"core.{code.value}.{status.value}",
        boundary_code=code,
        scope=CheckScope.CORE,
        source_context=source_context,
        destination_class=_DESTINATION_BY_BOUNDARY.get(code, DestinationClass.PEER_RANGE),
        expected=Outcome.UNREACHABLE,
        observed=None,
        status=status,
        elapsed_ms=0,
        diagnostic=sanitize_diagnostic(reason),
    )


def _source_label(range_id: int) -> str:
    """Return the bounded participant source-context label for a range."""
    return f"participant:range-{range_id}"


__all__ = ["ProbeLauncher", "RunOptions", "run_escape_validation"]
