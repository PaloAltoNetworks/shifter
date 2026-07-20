"""Tests for the scenario-neutral range-escape validation report contract.

The contract (`shared.range_escape`) is the closed, versioned, machine-readable
security report that the escape-validation suite emits (issue #1347). These tests
pin the verdict semantics, the one-range vs multi-range gate, JSON round-trip,
and the diagnostic sanitization that keeps token-shaped substrings out of the
report.
"""

from __future__ import annotations

import pytest

from shared.range_escape import (
    CONTRACT,
    PEER_DEPENDENT_BOUNDARIES,
    REQUIRED_CORE_BOUNDARIES,
    VERSION,
    BoundaryCode,
    CheckContext,
    CheckResult,
    CheckScope,
    CheckStatus,
    DestinationClass,
    EscapeContractError,
    EscapeReport,
    Outcome,
    SuiteMode,
    Verdict,
    contains_secret_shape,
    evaluate_check,
    sanitize_diagnostic,
)


def _ctx(
    check_id: str,
    boundary: BoundaryCode,
    destination: DestinationClass = DestinationClass.PLATFORM_POD,
) -> CheckContext:
    return CheckContext(
        check_id=check_id,
        boundary_code=boundary,
        scope=CheckScope.CORE,
        source_context="participant:range-1",
        destination_class=destination,
    )


def _core_pass(boundary: BoundaryCode) -> CheckResult:
    """A passing core check for ``boundary`` (blocked boundary observed unreachable)."""
    return evaluate_check(
        _ctx(f"core.{boundary.value}", boundary),
        expected=Outcome.UNREACHABLE,
        observed=Outcome.UNREACHABLE,
        elapsed_ms=12,
    )


def _control_pass() -> CheckResult:
    """A passing positive control (participant reached a known-live target)."""
    return evaluate_check(
        _ctx("control.probe_capability", BoundaryCode.PROBE_CONTROL, DestinationClass.CONTROL),
        expected=Outcome.REACHABLE,
        observed=Outcome.REACHABLE,
        elapsed_ms=5,
    )


def _all_required_core_pass() -> list[CheckResult]:
    return [_core_pass(code) for code in REQUIRED_CORE_BOUNDARIES]


def _all_peer_pass() -> list[CheckResult]:
    return [_core_pass(code) for code in PEER_DEPENDENT_BOUNDARIES]


def _report(mode: SuiteMode, checks: list[CheckResult], *, include_control: bool = True, **kw: object) -> EscapeReport:
    all_checks = [_control_pass(), *checks] if include_control else checks
    params: dict[str, object] = {
        "suite_id": "suite-abc",
        "mode": mode,
        "request_id": "req-1",
        "range_id": 1,
        "started_at": "2026-07-14T00:00:00Z",
        "ended_at": "2026-07-14T00:01:00Z",
        "checks": all_checks,
    }
    params.update(kw)
    return EscapeReport(**params)  # type: ignore[arg-type]


class TestVerdict:
    def test_one_range_passes_with_all_required_core_passing(self) -> None:
        report = _report(SuiteMode.ONE_RANGE, _all_required_core_pass())
        assert report.verdict is Verdict.PASSED

    def test_missing_positive_control_fails_closed(self) -> None:
        # Without a positive control the probe environment is unproven, so an
        # all-"secure" report must not pass.
        report = _report(SuiteMode.ONE_RANGE, _all_required_core_pass(), include_control=False)
        assert report.verdict is Verdict.FAILED

    def test_any_failed_check_fails_the_verdict(self) -> None:
        checks = _all_required_core_pass()
        checks.append(
            evaluate_check(
                _ctx("core.metadata_server.leaked", BoundaryCode.METADATA_SERVER, DestinationClass.METADATA),
                expected=Outcome.UNREACHABLE,
                observed=Outcome.REACHABLE,
                elapsed_ms=3,
            )
        )
        report = _report(SuiteMode.ONE_RANGE, checks)
        assert report.verdict is Verdict.FAILED

    def test_missing_required_core_boundary_fails(self) -> None:
        # Drop one required core boundary: coverage is incomplete, so the gate fails.
        partial = [c for c in _all_required_core_pass() if c.boundary_code != BoundaryCode.METADATA_SERVER]
        report = _report(SuiteMode.ONE_RANGE, partial)
        assert report.verdict is Verdict.FAILED

    def test_one_range_ignores_skipped_peer_checks(self) -> None:
        checks = _all_required_core_pass()
        checks.append(
            evaluate_check(
                _ctx(
                    "core.cross_range_private_ip.no_peer",
                    BoundaryCode.CROSS_RANGE_PRIVATE_IP,
                    DestinationClass.PEER_RANGE,
                ),
                expected=Outcome.UNREACHABLE,
                observed=None,
                status=CheckStatus.NOT_APPLICABLE,
                elapsed_ms=0,
                diagnostic="no peer range supplied",
            )
        )
        report = _report(SuiteMode.ONE_RANGE, checks)
        assert report.verdict is Verdict.PASSED

    def test_multi_range_requires_peer_checks_to_pass(self) -> None:
        report = _report(SuiteMode.MULTI_RANGE, _all_required_core_pass() + _all_peer_pass(), peer_range_ids=[2])
        assert report.verdict is Verdict.PASSED

    def test_multi_range_fails_when_peer_check_skipped(self) -> None:
        checks = _all_required_core_pass()
        # peer checks present but skipped: the >=2-range gate must not pass.
        for code in PEER_DEPENDENT_BOUNDARIES:
            checks.append(
                evaluate_check(
                    _ctx(f"core.{code.value}.skipped", code, DestinationClass.PEER_RANGE),
                    expected=Outcome.UNREACHABLE,
                    observed=None,
                    status=CheckStatus.SKIP,
                    elapsed_ms=0,
                    diagnostic="peer probe skipped",
                )
            )
        report = _report(SuiteMode.MULTI_RANGE, checks, peer_range_ids=[2])
        assert report.verdict is Verdict.FAILED

    def test_peer_boundaries_are_disjoint_from_required_core(self) -> None:
        assert REQUIRED_CORE_BOUNDARIES.isdisjoint(PEER_DEPENDENT_BOUNDARIES)


class TestEvaluateCheck:
    def test_status_derived_pass_when_observed_matches_expected(self) -> None:
        result = evaluate_check(
            _ctx("c1", BoundaryCode.INTERNET_EGRESS, DestinationClass.INTERNET),
            expected=Outcome.REACHABLE,
            observed=Outcome.REACHABLE,
            elapsed_ms=5,
        )
        assert result.status is CheckStatus.PASS

    def test_status_derived_fail_when_observed_differs(self) -> None:
        result = evaluate_check(
            _ctx("c2", BoundaryCode.CROSS_RANGE_DNS, DestinationClass.PEER_RANGE),
            expected=Outcome.UNREACHABLE,
            observed=Outcome.REACHABLE,
            elapsed_ms=5,
        )
        assert result.status is CheckStatus.FAIL

    def test_explicit_skip_requires_no_observed(self) -> None:
        result = evaluate_check(
            _ctx("c3", BoundaryCode.CROSS_RANGE_DNS, DestinationClass.PEER_RANGE),
            expected=Outcome.UNREACHABLE,
            observed=None,
            status=CheckStatus.SKIP,
            elapsed_ms=0,
        )
        assert result.status is CheckStatus.SKIP

    def test_missing_observed_without_explicit_status_is_rejected(self) -> None:
        context = _ctx("c4", BoundaryCode.CROSS_RANGE_DNS, DestinationClass.PEER_RANGE)
        with pytest.raises(EscapeContractError):
            evaluate_check(context, expected=Outcome.UNREACHABLE, observed=None, elapsed_ms=0)


class TestRoundTrip:
    def test_json_round_trip_preserves_report(self) -> None:
        report = _report(
            SuiteMode.MULTI_RANGE,
            _all_required_core_pass() + _all_peer_pass(),
            peer_request_ids=["req-2"],
            peer_range_ids=[2],
            policy_inputs={"egress_policy": "deny-all", "range_cell_result": "sha256:abc"},
        )
        restored = EscapeReport.from_json(report.to_json())
        assert restored.to_dict() == report.to_dict()

    def test_to_dict_includes_contract_version_and_verdict(self) -> None:
        report = _report(SuiteMode.ONE_RANGE, _all_required_core_pass())
        data = report.to_dict()
        assert data["contract"] == CONTRACT
        assert data["version"] == VERSION
        assert data["verdict"] == Verdict.PASSED.value

    def test_from_dict_rejects_unknown_boundary_code(self) -> None:
        report = _report(SuiteMode.ONE_RANGE, _all_required_core_pass())
        data = report.to_dict()
        data["checks"][0]["boundary_code"] = "not_a_real_boundary"
        with pytest.raises(EscapeContractError):
            EscapeReport.from_dict(data)


class TestSanitization:
    def test_diagnostic_collapses_newlines_and_bounds_length(self) -> None:
        raw = "line one\nline two\r\n" + ("x" * 500)
        clean = sanitize_diagnostic(raw, max_len=80)
        assert "\n" not in clean
        assert "\r" not in clean
        assert len(clean) <= 80

    def test_secret_shaped_substrings_are_redacted(self) -> None:
        token = "ya29." + "A" * 60
        clean = sanitize_diagnostic(f"metadata returned {token}")
        assert token not in clean
        assert not contains_secret_shape(clean)

    def test_contains_secret_shape_detects_tokens_and_ignores_benign(self) -> None:
        assert contains_secret_shape("Bearer " + "a" * 40)
        # Split so the file text is not a literal key marker (detect-private-key
        # pre-commit hook); the runtime string is the real PEM header.
        assert contains_secret_shape("-----BEGIN " + "PRIVATE KEY-----")
        assert not contains_secret_shape("cross_range_private_ip unreachable after 2s")
