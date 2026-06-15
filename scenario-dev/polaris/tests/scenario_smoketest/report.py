"""Per-challenge result aggregation and reporting.

A challenge result is one of:

* ``pass``      - the hint path produced the configured value.
* ``fail``      - the hint path produced a wrong or missing value.
* ``uncovered`` - no adapter is registered for the challenge. Per the issue,
  the coverage universe is derived from the board, so an uncovered challenge
  is a reported failure, never a silent skip.
* ``error``     - the adapter raised before producing a verdict.

Detail strings are expected to be redacted by the caller (see :mod:`compare`);
this module never reconstructs raw values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_FAILING = ("fail", "uncovered", "error")


@dataclass(frozen=True)
class ChallengeResult:
    """Outcome for a single challenge."""

    challenge_id: int
    name: str
    status: str
    detail: str


def summarize(results: list[ChallengeResult]) -> dict[str, int]:
    """Return per-status counts plus a ``total``."""
    counts = {"pass": 0, "fail": 0, "uncovered": 0, "error": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    counts["total"] = len(results)
    return counts


def aggregate_exit_code(results: list[ChallengeResult]) -> int:
    """Return 0 only when every challenge passed."""
    return 1 if any(r.status in _FAILING for r in results) else 0


def to_json(results: list[ChallengeResult]) -> list[dict]:
    """Render results as a redaction-safe JSON-serialisable list."""
    return [
        {
            "challenge_id": r.challenge_id,
            "name": r.name,
            "status": r.status,
            "detail": r.detail,
        }
        for r in results
    ]


def build_report(results: list[ChallengeResult]) -> str:
    """Render the human-readable per-challenge table plus an aggregate line."""
    lines = ["", "Pre-event scenario smoketest — per-challenge results", ""]
    for r in sorted(results, key=lambda x: x.challenge_id):
        marker = {
            "pass": "PASS",
            "fail": "FAIL",
            "uncovered": "UNCOVERED",
            "error": "ERROR",
        }.get(r.status, r.status.upper())
        lines.append(f"  [{marker:<9}] #{r.challenge_id:<3} {r.name} — {r.detail}")

    counts = summarize(results)
    lines.append("")
    lines.append(
        "  {pass} pass / {fail} fail / {uncovered} uncovered / "
        "{error} error  ({total} total)".format(**counts)
    )
    verdict = "PASS" if aggregate_exit_code(results) == 0 else "FAIL"
    lines.append(f"  scenario smoketest: {verdict}")
    lines.append("")
    return "\n".join(lines)


def write_json_report(results: list[ChallengeResult], path: str) -> None:
    """Write the redacted JSON report to ``path``."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(to_json(results), handle, indent=2)
        handle.write("\n")
