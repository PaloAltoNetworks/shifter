"""Scoring-mode strategy dispatch (CTF-002, CTF-201).

Solve-time point calculation is routed through a mode strategy so an event's
configured ``scoring_mode`` — not convention — decides how a correct solve is
scored. Only ``standard`` is implemented today (CTF-201: the challenge's fixed
point value, less cumulative hint penalty, independent of solve count); the
boundary exists so a future mode (dynamic, etc. — CTF-002) is one added enum
value plus one strategy, with no change to the submission service, event views,
templates, scoreboards, or leaderboard maintenance.

The strategy is deterministic and side-effect free: ``submit_flag`` computes the
solve value under the participant ``select_for_update`` lock, so a strategy must
not perform I/O or unbounded work.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from ctf.enums import ScoringMode

if TYPE_CHECKING:
    from ctf.models import CTFChallenge, CTFEvent

logger = logging.getLogger(__name__)


class ScoringStrategy(Protocol):
    """Computes the points a correct solve awards, given the hint penalty."""

    def points_for_solve(self, challenge: CTFChallenge, total_hint_penalty: int) -> int:
        """Return the points to award for a correct solve of ``challenge``."""
        ...


class StandardScoringStrategy:
    """CTF-201 standard scoring: fixed challenge value, less hint penalty.

    The base value is ``CTFChallenge.points`` and does not depend on solve
    count. Hint penalties stay an explicit modifier via the existing
    ``calculate_points_with_penalty`` (no duplicated hint math here).
    """

    @staticmethod
    def points_for_solve(challenge: CTFChallenge, total_hint_penalty: int) -> int:
        return challenge.calculate_points_with_penalty(total_hint_penalty)


_STRATEGIES: dict[ScoringMode, ScoringStrategy] = {
    ScoringMode.STANDARD: StandardScoringStrategy(),
}


def get_scoring_strategy(mode: str) -> ScoringStrategy:
    """Resolve the scoring strategy for a mode value.

    Falls back to standard scoring for an unknown or unset mode. Writes are
    validated to a known mode at the event-config boundary (CTFValidationError →
    400), so an unknown value here means data drift; falling back keeps a live
    solve from failing rather than 500-ing mid-competition.
    """
    try:
        return _STRATEGIES[ScoringMode(mode)]
    except (ValueError, KeyError):
        logger.warning("Unknown scoring mode %r; falling back to standard scoring", mode)
        return _STRATEGIES[ScoringMode.STANDARD]


def calculate_solve_points(event: CTFEvent, challenge: CTFChallenge, total_hint_penalty: int) -> int:
    """Points to award for a correct solve, dispatched by the event's mode.

    Args:
        event: The event whose ``scoring_mode`` selects the strategy.
        challenge: The solved challenge.
        total_hint_penalty: Cumulative penalty of unlocked hints (0-100+).

    Returns:
        Points to award (never negative).
    """
    return get_scoring_strategy(event.scoring_mode).points_for_solve(challenge, total_hint_penalty)
