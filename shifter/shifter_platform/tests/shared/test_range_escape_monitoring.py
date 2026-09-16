"""Tests for the range-escape containment-signal seam (issue #1295, interface to #2087)."""

from __future__ import annotations

import logging
import threading

from shared.range_escape import (
    BoundaryCode,
    CheckContext,
    CheckScope,
    CheckStatus,
    DestinationClass,
    EscapeReport,
    Outcome,
    SuiteMode,
    Verdict,
    evaluate_check,
)
from shared.range_escape_monitoring import LoggingContainmentSink, emit_containment_signal

_LOGGER_NAME = "shifter.range_escape.containment"


def _ctx(boundary: BoundaryCode, destination: DestinationClass = DestinationClass.PLATFORM_POD) -> CheckContext:
    return CheckContext(
        check_id=f"core.{boundary.value}",
        boundary_code=boundary,
        scope=CheckScope.CORE,
        source_context="participant:range-1",
        destination_class=destination,
    )


def _pass(boundary: BoundaryCode) -> object:
    return evaluate_check(_ctx(boundary), expected=Outcome.UNREACHABLE, observed=Outcome.UNREACHABLE, elapsed_ms=1)


def _fail(boundary: BoundaryCode) -> object:
    return evaluate_check(_ctx(boundary), expected=Outcome.UNREACHABLE, observed=Outcome.REACHABLE, elapsed_ms=1)


def _control() -> object:
    return evaluate_check(
        _ctx(BoundaryCode.PROBE_CONTROL, DestinationClass.CONTROL),
        expected=Outcome.REACHABLE,
        observed=Outcome.REACHABLE,
        elapsed_ms=1,
    )


def _report(checks: list) -> EscapeReport:
    return EscapeReport(
        suite_id="suite-abc",
        mode=SuiteMode.ONE_RANGE,
        request_id="req-1",
        range_id=1,
        started_at="2026-09-06T00:00:00Z",
        ended_at="2026-09-06T00:01:00Z",
        checks=checks,
    )


class _CapturingSink:
    def __init__(self) -> None:
        self.reports: list[EscapeReport] = []

    def record(self, report: EscapeReport) -> None:
        self.reports.append(report)


class _RaisingSink:
    def record(self, report: EscapeReport) -> None:
        raise RuntimeError("sink down")


def test_emit_hands_report_to_sink_and_returns_verdict() -> None:
    report = _report([_control(), _pass(BoundaryCode.METADATA_SERVER)])
    sink = _CapturingSink()

    verdict = emit_containment_signal(report, sink)

    assert sink.reports == [report]
    assert verdict is report.verdict


def test_emit_is_fail_safe_when_the_sink_raises(caplog) -> None:
    # A broken or slow monitor must never break range-escape validation: the emit
    # swallows the sink error, logs it (so #2087 can alert on collector loss), and
    # still returns the report's verdict for the caller's own gate.
    report = _report([_control(), _pass(BoundaryCode.METADATA_SERVER)])

    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        verdict = emit_containment_signal(report, _RaisingSink())

    assert verdict is report.verdict
    assert any("containment sink failed" in record.getMessage() for record in caplog.records)


def test_logging_sink_emits_bounded_sanitized_summary(caplog) -> None:
    report = _report([_control(), _fail(BoundaryCode.METADATA_SERVER), _pass(BoundaryCode.INTERNET_EGRESS)])

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        LoggingContainmentSink().record(report)

    record = next(r for r in caplog.records if r.getMessage() == "range-escape containment signal")
    assert record.range_escape_contract == report.contract
    assert record.verdict == report.verdict.value == Verdict.FAILED.value
    assert "metadata_server" in record.failed_boundaries
    assert "internet_egress" not in record.failed_boundaries
    assert record.boundary_status_counts.get(CheckStatus.FAIL.value) == 1
    assert record.range_id == 1
    # The bounded-payload contract: only codes and counts, never raw per-check
    # fields (diagnostics, the full checks list) that would widen what lands in
    # Cloud Logging.
    assert "diagnostic" not in record.__dict__
    assert "checks" not in record.__dict__


def test_emit_does_not_block_on_a_slow_sink(caplog) -> None:
    # A stalled or network-backed sink must not delay validation past the
    # deadline: the emit returns with the verdict and logs a slow-collector
    # warning rather than blocking on the sink.
    report = _report([_control(), _pass(BoundaryCode.METADATA_SERVER)])
    release = threading.Event()

    class _StallingSink:
        def record(self, report: EscapeReport) -> None:
            release.wait(timeout=30)

    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            verdict = emit_containment_signal(report, _StallingSink(), timeout_s=0.05)

        assert verdict is report.verdict
        assert any("did not complete within" in record.getMessage() for record in caplog.records)
    finally:
        release.set()


def test_default_sink_is_the_logging_baseline(caplog) -> None:
    report = _report([_control(), _pass(BoundaryCode.METADATA_SERVER)])

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        emit_containment_signal(report)

    assert any(r.getMessage() == "range-escape containment signal" for r in caplog.records)
