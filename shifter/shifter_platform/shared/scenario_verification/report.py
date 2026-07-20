"""Human and JSON renderers over the same redacted report DTO."""

from __future__ import annotations

import json

from .framework import VerificationReport, aggregate_exit_code


def render_human(report: VerificationReport) -> str:
    """Render deterministic line-safe operator output with no raw evidence."""
    if not isinstance(report, VerificationReport):
        raise TypeError("report must be VerificationReport")
    lines = [
        f"scenario verification report v{report.schema_version}",
        (
            f"selection distribution={report.distribution} "
            f"distribution_version={report.distribution_version} "
            f"entry_point={report.entry_point} plugin_id={report.plugin_id} "
            f"plugin_version={report.plugin_version}"
        ),
    ]
    lines.extend(
        f"[{check.status.value.upper()}] {check.adapter_id} reason={check.reason.value} duration_ms={check.duration_ms}"
        for check in report.checks
    )
    counts = report.counts
    lines.append(
        "summary "
        f"pass={counts['pass']} fail={counts['fail']} blocked={counts['blocked']} "
        f"error={counts['error']} total={counts['total']} "
        f"duration_ms={report.duration_ms} exit={aggregate_exit_code(report)}"
    )
    return "\n".join(lines) + "\n"


def render_json(report: VerificationReport) -> str:
    """Render the report DTO through an explicit allowlisted schema."""
    if not isinstance(report, VerificationReport):
        raise TypeError("report must be VerificationReport")
    payload = {
        "schema_version": report.schema_version,
        "selection": {
            "distribution": report.distribution,
            "distribution_version": report.distribution_version,
            "entry_point": report.entry_point,
            "plugin_id": report.plugin_id,
            "plugin_version": report.plugin_version,
        },
        "checks": [
            {
                "adapter_id": check.adapter_id,
                "status": check.status.value,
                "reason": check.reason.value,
                "duration_ms": check.duration_ms,
            }
            for check in report.checks
        ],
        "summary": report.counts,
        "duration_ms": report.duration_ms,
        "exit_code": aggregate_exit_code(report),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


__all__ = ["render_human", "render_json"]
