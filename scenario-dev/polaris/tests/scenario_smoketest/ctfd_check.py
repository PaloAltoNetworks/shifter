"""Read-only CTFd flag-row readback.

Implements ``lessons-4.md`` pre-flight checklist item 4: for every CTFd
challenge, ``GET /challenges/{id}/flags`` and assert the row set is non-empty.
This catches the regression where a ``sync_polaris_ctfd.py`` re-sync silently
dropped flag rows and shipped 38/39 challenges unsubmittable.

This module is strictly read-only. It never creates, patches, or deletes any
CTFd object — flag repair belongs in ``scripts/ctfd-workshop/*``. CTFd
pagination is silent and capped, so ``/challenges`` is walked page by page.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagRowResult:
    """Whether one CTFd challenge has any flag rows configured."""

    challenge_id: int
    has_flags: bool
    flag_count: int
    detail: str


def _all_challenge_ids(client) -> list[int]:
    ids: list[int] = []
    page = 1
    while True:
        payload = client.get("/challenges", query={"page": page})
        for entry in payload.get("data", []):
            cid = entry.get("id")
            if isinstance(cid, int):
                ids.append(cid)
        nxt = payload.get("meta", {}).get("pagination", {}).get("next")
        if not nxt:
            break
        page = nxt
    return ids


def check_flags(client, challenge_ids: list[int] | None = None) -> list[FlagRowResult]:
    """Return a flag-row result for every CTFd challenge (or a filtered set)."""
    ids = challenge_ids if challenge_ids is not None else _all_challenge_ids(client)
    results: list[FlagRowResult] = []
    for cid in ids:
        payload = client.get(f"/challenges/{cid}/flags")
        rows = payload.get("data", [])
        count = len(rows)
        results.append(
            FlagRowResult(
                challenge_id=cid,
                has_flags=count > 0,
                flag_count=count,
                detail=(
                    f"{count} flag row(s) configured"
                    if count
                    else "NO flag rows — challenge is unsubmittable"
                ),
            )
        )
    return results


def exit_code(results: list[FlagRowResult]) -> int:
    """Return 0 only when every checked challenge has at least one flag row."""
    return 1 if any(not r.has_flags for r in results) else 0


def build_report(results: list[FlagRowResult]) -> str:
    """Render the human-readable CTFd flag-row readback table."""
    lines = ["", "CTFd flag-row readback (read-only)", ""]
    for r in sorted(results, key=lambda x: x.challenge_id):
        marker = "OK" if r.has_flags else "EMPTY"
        lines.append(f"  [{marker:<5}] challenge #{r.challenge_id} — {r.detail}")
    empty = sum(1 for r in results if not r.has_flags)
    verdict = "PASS" if empty == 0 else "FAIL"
    lines.append("")
    lines.append(
        f"  {len(results) - empty}/{len(results)} challenges have flag rows"
    )
    lines.append(f"  CTFd flag-row readback: {verdict}")
    lines.append("")
    return "\n".join(lines)
