"""CTF Scoring service.

Business logic for score calculation, leaderboards, ranks, statistics, and the
materialized-leaderboard maintenance helpers (issue #850).

Split from the monolithic ``ctf/services/scoring.py`` into a package (issue
#891, python:S104) across cohesive submodules:

- ``_read``: scoreboard / team-scoreboard / participant-rank reads (materialized
  hot path + authoritative recompute fallback) and ``calculate_score``;
- ``_stats``: challenge / event statistics and the per-participant timeline;
- ``_maintenance``: recompute helpers that rebuild the materialized columns.

Every public name is re-exported here so ``from ctf.services.scoring import X``
keeps working unchanged. The model classes are re-exported too so existing
``unittest.mock.patch("ctf.services.scoring.CTF<Model>.objects")`` test seams
continue to resolve (the patch targets an attribute on the shared model class,
so submodules see it regardless of which namespace it was reached through).
"""

from __future__ import annotations

# Re-exported model seams: preserve patch("ctf.services.scoring.CTF<Model>...")
# targets used by the scoring/statistics/timeline test suites.
from ctf.models import (  # noqa: F401
    CTFAward,
    CTFParticipant,
    CTFSubmission,
    CTFTeam,
)

from ._maintenance import (
    recompute_event_leaderboard,
    recompute_participant_score,
    recompute_team_score,
)
from ._read import (
    calculate_score,
    get_participant_rank,
    get_scoreboard,
    get_team_scoreboard,
)
from ._stats import (
    get_challenge_statistics,
    get_event_statistics,
    get_score_timeline,
)
from ._strategy import (
    calculate_solve_points,
    get_scoring_strategy,
)

__all__ = [
    "calculate_score",
    "calculate_solve_points",
    "get_challenge_statistics",
    "get_event_statistics",
    "get_participant_rank",
    "get_score_timeline",
    "get_scoreboard",
    "get_scoring_strategy",
    "get_team_scoreboard",
    "recompute_event_leaderboard",
    "recompute_participant_score",
    "recompute_team_score",
]
