"""Containment-signal seam for range-escape reports (issue #1295, interface to #2087).

The escape-validation suite (#1347) produces a versioned, sanitized
:class:`shared.range_escape.EscapeReport` as a pre-event gate. #2087 (continuous
range-escape monitoring and containment response) consumes that same report as a
runtime containment signal. This module is the stable, tested seam between the
two so neither couples to the other's internals:

- :class:`ContainmentSignalSink` is the consumer interface #2087 implements (its
  sensor/monitor pipeline, alerting, and containment-response hooks).
- :class:`LoggingContainmentSink` is the default: a bounded, sanitized structured
  log record. It is the modest GCP-native baseline (#2087 acceptance) that Cloud
  Logging ingests without requiring a SIEM.
- :func:`emit_containment_signal` is the single call sites use to hand a report
  to the configured sink.

The report is already sanitized by ``shared.range_escape`` (bounded diagnostics,
no raw guest output, credentials, secrets, tokens, or metadata bodies), so the
signal a sink receives carries none of those.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from shared.range_escape import CheckStatus, EscapeReport, Verdict

_LOGGER = logging.getLogger("shifter.range_escape.containment")

# Delivery to a sink is bounded so a slow or stalled collector (a network-backed
# #2087 sink or a blocking logging handler) cannot delay range-escape validation
# past this deadline.
_DEFAULT_SINK_TIMEOUT_S = 5.0


class ContainmentSignalSink(Protocol):
    """Consumes a range-escape report as a containment signal (#2087 implements)."""

    def record(self, report: EscapeReport) -> None: ...


class LoggingContainmentSink:
    """Default sink: emit a bounded, sanitized structured summary via stdlib logging.

    The record carries only the versioned contract identity, range/generation
    attribution, the verdict, per-status boundary counts, and the failed boundary
    codes. It never carries raw diagnostics: the payload is derived from the
    already-sanitized report, and only codes and counts are emitted.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger if logger is not None else _LOGGER

    def record(self, report: EscapeReport) -> None:
        counts: dict[str, int] = {}
        for check in report.checks:
            counts[check.status.value] = counts.get(check.status.value, 0) + 1
        failed_boundaries = sorted({c.boundary_code.value for c in report.checks if c.status == CheckStatus.FAIL})
        self._logger.info(
            "range-escape containment signal",
            extra={
                "range_escape_contract": report.contract,
                "range_escape_version": report.version,
                "suite_id": report.suite_id,
                "range_id": report.range_id,
                "request_id": report.request_id,
                "mode": report.mode.value,
                "verdict": report.verdict.value,
                "boundary_status_counts": counts,
                "failed_boundaries": failed_boundaries,
            },
        )


def emit_containment_signal(
    report: EscapeReport,
    sink: ContainmentSignalSink | None = None,
    *,
    timeout_s: float = _DEFAULT_SINK_TIMEOUT_S,
) -> Verdict:
    """Hand a range-escape report to the containment sink and return its verdict.

    The seam is fail-safe for the producer against both a broken and a slow
    monitor. Delivery runs on a bounded daemon thread: a sink error is logged and
    swallowed, and a sink that does not return within ``timeout_s`` does not delay
    validation past that deadline (the emit returns and logs a slow-collector
    warning that #2087 alerts on; the daemon thread never blocks process exit).
    The caller always receives the report's verdict for its own gate. The default
    sink is the structured-logging baseline; #2087 injects its own sink to drive
    continuous monitoring and containment response.
    """
    active = sink if sink is not None else LoggingContainmentSink()

    def _deliver() -> None:
        """Deliver the report to the sink, swallowing and logging any sink error."""
        try:
            active.record(report)
        except Exception:
            _LOGGER.exception("range-escape containment sink failed", extra={"suite_id": report.suite_id})

    worker = threading.Thread(target=_deliver, name="range-escape-containment-sink", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        _LOGGER.warning(
            "range-escape containment sink did not complete within %.1fs; continuing",
            timeout_s,
            extra={"suite_id": report.suite_id},
        )
    return report.verdict


__all__ = ["ContainmentSignalSink", "LoggingContainmentSink", "emit_containment_signal"]
