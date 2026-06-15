"""CTFd challenge-board parsing.

The board JSON (``ctfd-challenges.json`` and optional ``ctfd-onboarding.json``)
is the single source of challenge metadata. This module derives the challenge
universe and the configured static flag per challenge; it never duplicates
challenge names, categories, hints, or prerequisites into a second schema.

Static-flag extraction follows the ``verify_flags_baked.static_flag`` shape:
a challenge must carry exactly one ``static`` flag for the harness to use it as
an equality target. Anything else (zero, many, or non-static) is reported as a
missing comparison target and fails closed in :mod:`compare`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Challenge:
    """One CTFd challenge as seen by the harness."""

    id: int
    name: str
    category: str
    static_flag: str | None


def _static_flag(challenge: dict) -> str | None:
    """Return the single static-flag content, or None when not exactly one."""
    static = [
        f for f in challenge.get("flags", []) if f.get("type") == "static"
    ]
    if len(static) != 1:
        return None
    content = static[0].get("content")
    return content or None


def _challenges_from(path: Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "challenges" not in payload or not isinstance(payload["challenges"], list):
        raise ValueError(f"{path}: missing or invalid 'challenges' list")
    return payload["challenges"]


def load_board(
    challenges_path: str | Path,
    onboarding_path: str | Path | None = None,
) -> list[Challenge]:
    """Parse the board JSON into a list of :class:`Challenge`.

    When ``onboarding_path`` is given its challenges are merged into the
    universe. Duplicate challenge ids across the merged set are rejected:
    an ambiguous id makes per-challenge results meaningless.
    """
    raw = list(_challenges_from(challenges_path))
    if onboarding_path is not None:
        raw.extend(_challenges_from(onboarding_path))

    challenges: list[Challenge] = []
    seen: set[int] = set()
    for entry in raw:
        cid = entry.get("id")
        if not isinstance(cid, int):
            raise ValueError(f"challenge has non-integer id: {entry.get('name')!r}")
        if cid in seen:
            raise ValueError(f"duplicate challenge id {cid}")
        seen.add(cid)
        challenges.append(
            Challenge(
                id=cid,
                name=str(entry.get("name", "")),
                category=str(entry.get("category", "")),
                static_flag=_static_flag(entry),
            )
        )
    return challenges
