"""Orchestration: walk the challenge universe and run each adapter.

The universe comes from the board (:mod:`board`). For every challenge the
harness looks up a registered adapter; a challenge with no adapter is
``uncovered`` (a failure). A covered challenge's adapter is executed against
the range and its produced value is compared (:mod:`compare`) to the board's
configured static flag, or to the adapter's recorded answer for ``answer``
challenges.
"""

from __future__ import annotations

from . import compare
from .adapters import ADAPTERS, AdapterContext
from .board import Challenge
from .report import ChallengeResult


def run_smoketest(
    challenges: list[Challenge],
    runner,
    *,
    hosts: dict[str, str],
    dns: str = "172.20.0.2",
    only_ids: set[int] | None = None,
) -> list[ChallengeResult]:
    """Execute every covered challenge and return per-challenge results."""
    results: list[ChallengeResult] = []
    for challenge in challenges:
        if only_ids is not None and challenge.id not in only_ids:
            continue

        adapter = ADAPTERS.get(challenge.id)
        if adapter is None:
            results.append(
                ChallengeResult(
                    challenge.id,
                    challenge.name,
                    "uncovered",
                    "no adapter registered — challenge path is unverified",
                )
            )
            continue

        ctx = AdapterContext(runner=runner, hosts=hosts, dns=dns)
        try:
            produced = adapter.solve(ctx)
        except Exception as exc:  # noqa: BLE001 - adapter faults must not abort the sweep
            results.append(
                ChallengeResult(
                    challenge.id,
                    challenge.name,
                    "error",
                    f"adapter raised {type(exc).__name__}",
                )
            )
            continue

        if adapter.value_kind == "flag":
            expected = challenge.static_flag
        else:
            expected = adapter.expected_answer

        verdict = compare.compare(produced.value, expected, adapter.value_kind)
        detail = verdict.detail
        if produced.note:
            detail = f"{detail} [{produced.note}]"
        results.append(
            ChallengeResult(
                challenge.id,
                challenge.name,
                "pass" if verdict.status == "pass" else "fail",
                detail,
            )
        )
    return results
