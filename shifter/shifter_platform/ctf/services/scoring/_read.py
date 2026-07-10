"""CTF scoreboard and rank read paths.

Two read strategies live here (issue #850):

- **Materialized (hot path):** for the live, unfrozen board the per-participant
  and per-team score / solve-count / last-solve state is read straight from the
  denormalized ``cached_*`` columns (an indexed ``ORDER BY``), and a
  participant's rank is a single ``COUNT`` of competitors ranking above them.
  This removes the full-board recompute that previously ran on every flag
  submission, dashboard load, and 15s scoreboard poll.
- **Recompute (cold path):** frozen boards (``freeze_at`` set) and bracket-
  filtered team boards cannot be served from "current" materialized state, so
  they fall back to the exact authoritative aggregation over
  ``CTFSubmission`` / ``CTFAward``. These paths preserve freeze / bracket /
  visibility semantics unchanged.

The materialized columns are maintained by ``_maintenance`` and are always
rebuildable from the authoritative rows, so the two strategies agree.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import (
    Count,
    DateTimeField,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from ctf.models import CTFAward, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.participant import eligible_participant_q

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Sentinel used to rank participants with no solves last on the tie-break. A
# null last-solve compares as "latest". Coalescing to this sentinel (rather than
# relying on raw ``ORDER BY``) keeps no-solve rows last on every backend:
# Postgres defaults to NULLS LAST for ASC, but SQLite (used by the test suite)
# defaults to NULLS FIRST. Production behavior on Postgres is unchanged.
_RANK_NULL_LAST = datetime(9999, 12, 31, tzinfo=UTC)


def _nulls_last(expr: str | F) -> Coalesce:
    """Coalesce a possibly-null last-solve expression to the far-future sentinel.

    Used as a secondary ORDER BY key so the materialized board, the recompute
    board, and the rank COUNT all place no-solve rows last identically across
    database backends. ``expr`` is a field-name string or an ``F`` expression.
    """
    return Coalesce(expr, Value(_RANK_NULL_LAST, output_field=DateTimeField()))


def calculate_score(participant_id: UUID) -> int:
    """Calculate total score for a participant (submissions + awards).

    Authoritative per-participant aggregate (cheap, indexed by participant).
    Used for the score value shown on the dashboard and submit response; rank
    and the full board read the materialized columns instead.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Total score as integer.
    """
    submission_total = CTFSubmission.objects.filter(
        participant_id=participant_id,
        is_correct=True,
    ).aggregate(total=Coalesce(Sum("points_awarded"), 0))["total"]

    award_total = CTFAward.objects.filter(
        participant_id=participant_id,
    ).aggregate(total=Coalesce(Sum("points"), 0))["total"]

    return submission_total + award_total


def _build_scoreboard_rows(participants: Iterable[Any]) -> list[dict[str, Any]]:
    """Rank an ordered participant queryset, sharing a rank on (score, last-solve) ties.

    Rows are CTFParticipant instances carrying ``computed_score`` / ``solve_count``
    / ``last_solve_time`` attributes (annotations on both the materialized and
    recompute paths); typed as Any because those are dynamic query annotations.
    """
    scoreboard: list[dict[str, Any]] = []
    current_rank = 0
    last_score = None
    last_time = None
    for i, p in enumerate(participants):
        if p.computed_score != last_score or p.last_solve_time != last_time:
            current_rank = i + 1
        scoreboard.append(
            {
                "rank": current_rank,
                "participant_id": str(p.id),
                "name": p.name,
                "team_name": p.team.name if p.team else None,
                "bracket_name": p.bracket.name if p.bracket else None,
                "score": p.computed_score,
                "solve_count": p.solve_count,
                "last_solve": p.last_solve_time.isoformat() if p.last_solve_time else None,
            }
        )
        last_score = p.computed_score
        last_time = p.last_solve_time
    return scoreboard


def _build_team_scoreboard_rows(teams: Iterable[Any]) -> list[dict[str, Any]]:
    """Rank an ordered team queryset, sharing a rank on (score, last-solve) ties.

    Rows are CTFTeam instances carrying ``computed_score`` / ``solve_count`` /
    ``computed_member_count`` / ``last_solve_time`` attributes (annotations on
    both the materialized and recompute paths).
    """
    scoreboard: list[dict[str, Any]] = []
    current_rank = 0
    last_score = None
    last_time = None
    for i, t in enumerate(teams):
        if t.computed_score != last_score or t.last_solve_time != last_time:
            current_rank = i + 1
        scoreboard.append(
            {
                "rank": current_rank,
                "team_id": str(t.id),
                "name": t.name,
                "score": t.computed_score,
                "solve_count": t.solve_count,
                "member_count": t.computed_member_count,
                "last_solve": t.last_solve_time.isoformat() if t.last_solve_time else None,
            }
        )
        last_score = t.computed_score
        last_time = t.last_solve_time
    return scoreboard


def get_scoreboard(
    event_id: UUID,
    limit: int | None = None,
    freeze_at: datetime | None = None,
    bracket_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Get the individual scoreboard for an event.

    Ranked list of participants with scores; tie-breaker is earlier last solve.
    The live (no freeze) board is served from the materialized columns; a frozen
    board recomputes from authoritative rows as of ``freeze_at``. Bracket
    filtering works on both paths because a participant's score is
    bracket-independent.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.
        freeze_at: Optional freeze cutoff. When set, only submissions/awards
            before this time are counted (recompute path).
        bracket_id: Optional bracket filter.

    Returns:
        List of dicts with rank, participant info, score, and solve count.
    """
    logger.debug("Getting scoreboard for event %s", event_id)
    if freeze_at is None:
        return _materialized_scoreboard(event_id, limit, bracket_id)
    return _recompute_scoreboard(event_id, limit, freeze_at, bracket_id)


def _materialized_scoreboard(
    event_id: UUID,
    limit: int | None,
    bracket_id: UUID | None,
) -> list[dict[str, Any]]:
    """Live individual scoreboard read straight from the materialized columns."""
    base_filter: dict[str, Any] = {"event_id": event_id}
    if bracket_id is not None:
        base_filter["bracket_id"] = bracket_id

    participants = (
        CTFParticipant.objects.filter(eligible_participant_q(), **base_filter)
        .annotate(
            computed_score=F("cached_score"),
            solve_count=F("cached_solve_count"),
            last_solve_time=F("last_solve_at"),
            order_last_solve=_nulls_last("last_solve_at"),
        )
        .order_by("-cached_score", "order_last_solve")
        .select_related("team", "bracket")
    )
    if limit:
        participants = participants[:limit]
    return _build_scoreboard_rows(participants)


def _recompute_scoreboard(
    event_id: UUID,
    limit: int | None,
    freeze_at: datetime,
    bracket_id: UUID | None,
) -> list[dict[str, Any]]:
    """Authoritative individual scoreboard, recomputed as of ``freeze_at``.

    Annotating both submissions and awards on the same participant queryset
    would join them in one SQL query, so a participant with both a solve and an
    award produces a cartesian product that inflates both score and counts.
    Pre-aggregate via per-participant subqueries on CTFSubmission and CTFAward.
    """
    submission_qs = CTFSubmission.objects.filter(
        is_correct=True,
        participant_id=OuterRef("pk"),
        submitted_at__lt=freeze_at,
    )
    award_qs = CTFAward.objects.filter(participant_id=OuterRef("pk"), created_at__lt=freeze_at)

    base_filter: dict[str, Any] = {"event_id": event_id}
    if bracket_id is not None:
        base_filter["bracket_id"] = bracket_id

    participants = (
        CTFParticipant.objects.filter(eligible_participant_q(), **base_filter)
        .annotate(
            submission_score=Coalesce(
                Subquery(
                    submission_qs.order_by()
                    .values("participant_id")
                    .annotate(t=Coalesce(Sum("points_awarded"), 0))
                    .values("t"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            award_points=Coalesce(
                Subquery(
                    award_qs.order_by().values("participant_id").annotate(t=Coalesce(Sum("points"), 0)).values("t"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            computed_score=F("submission_score") + F("award_points"),
            solve_count=Coalesce(
                Subquery(
                    submission_qs.order_by().values("participant_id").annotate(c=Count("id")).values("c"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            last_solve_time=Subquery(
                submission_qs.order_by().values("participant_id").annotate(m=Max("submitted_at")).values("m"),
            ),
        )
        .annotate(order_last_solve=_nulls_last(F("last_solve_time")))
        .order_by("-computed_score", "order_last_solve")
        .select_related("team", "bracket")
    )

    if limit:
        participants = participants[:limit]

    return _build_scoreboard_rows(participants)


def get_team_scoreboard(
    event_id: UUID,
    limit: int | None = None,
    freeze_at: datetime | None = None,
    bracket_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Get the team scoreboard for an event.

    Aggregates scores across team members; tie-breaker is earlier last solve.
    The live, full-event board (no freeze, no bracket) is served from the
    materialized team columns; frozen or bracket-filtered boards recompute from
    authoritative rows, because a bracket view sums only the bracket's members
    and a frozen view is as of a cutoff.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.
        freeze_at: Optional freeze cutoff (recompute path).
        bracket_id: Optional bracket filter (recompute path).

    Returns:
        List of dicts with rank, team info, score, and member count.
    """
    logger.debug("Getting team scoreboard for event %s", event_id)
    if freeze_at is None and bracket_id is None:
        return _materialized_team_scoreboard(event_id, limit)
    return _recompute_team_scoreboard(event_id, limit, freeze_at, bracket_id)


def _materialized_team_scoreboard(event_id: UUID, limit: int | None) -> list[dict[str, Any]]:
    """Live team scoreboard read straight from the materialized columns."""
    teams = (
        CTFTeam.objects.filter(event_id=event_id)
        .annotate(
            computed_score=F("cached_score"),
            solve_count=F("cached_solve_count"),
            computed_member_count=F("cached_member_count"),
            last_solve_time=F("last_solve_at"),
            order_last_solve=_nulls_last("last_solve_at"),
        )
        .order_by("-cached_score", "order_last_solve")
    )
    if limit:
        teams = teams[:limit]
    return _build_team_scoreboard_rows(teams)


def _recompute_team_scoreboard(
    event_id: UUID,
    limit: int | None,
    freeze_at: datetime | None,
    bracket_id: UUID | None,
) -> list[dict[str, Any]]:
    """Authoritative team scoreboard, recomputed (frozen and/or bracket-filtered).

    Pre-aggregate submissions and awards as separate per-team subqueries (each
    over its own join) and add them in Python, so a member with both a solve and
    an award does not cause cartesian-product row multiplication. Eligibility is
    applied inside each subquery so disqualified members do not leak into totals.
    """
    member_eligibility_via_team = eligible_participant_q("members__")

    submission_qs = CTFSubmission.objects.filter(
        is_correct=True,
        participant__team_id=OuterRef("pk"),
    ).filter(eligible_participant_q("participant__"))
    if freeze_at:
        submission_qs = submission_qs.filter(submitted_at__lt=freeze_at)
    if bracket_id is not None:
        submission_qs = submission_qs.filter(participant__bracket_id=bracket_id)

    award_qs = CTFAward.objects.filter(participant__team_id=OuterRef("pk")).filter(
        eligible_participant_q("participant__")
    )
    if freeze_at:
        award_qs = award_qs.filter(created_at__lt=freeze_at)
    if bracket_id is not None:
        award_qs = award_qs.filter(participant__bracket_id=bracket_id)

    member_count_filter = member_eligibility_via_team
    if bracket_id is not None:
        member_count_filter &= Q(members__bracket_id=bracket_id)

    teams_qs = CTFTeam.objects.filter(event_id=event_id).annotate(
        award_points=Coalesce(
            Subquery(
                award_qs.order_by()
                .values("participant__team_id")
                .annotate(total=Coalesce(Sum("points"), 0))
                .values("total"),
                output_field=IntegerField(),
            ),
            0,
        ),
        solve_count=Coalesce(
            Subquery(
                submission_qs.order_by()
                .values("participant__team_id")
                .annotate(c=Count("challenge_id", distinct=True))
                .values("c"),
                output_field=IntegerField(),
            ),
            0,
        ),
        computed_member_count=Count("members", filter=member_count_filter, distinct=True),
        last_solve_time=Subquery(
            submission_qs.order_by().values("participant__team_id").annotate(m=Max("submitted_at")).values("m"),
        ),
        # Placeholder; the real, challenge-deduped score is set in Python below
        # (the DB cannot Sum a per-challenge Max in one query).
        computed_score=Value(0, output_field=IntegerField()),
    )

    # Deduped submission points per team: a challenge solved by more than one
    # teammate counts once, at its best (max) points (#1138). The DB cannot
    # Sum() a Max() annotation in one query, so group by (team, challenge) ->
    # max in the DB and sum the per-challenge maxes per team in Python. This is
    # the cold (frozen / bracket) path, so per-team iteration is acceptable.
    dedupe_qs = CTFSubmission.objects.filter(
        is_correct=True,
        participant__team__event_id=event_id,
    ).filter(eligible_participant_q("participant__"))
    if freeze_at:
        dedupe_qs = dedupe_qs.filter(submitted_at__lt=freeze_at)
    if bracket_id is not None:
        dedupe_qs = dedupe_qs.filter(participant__bracket_id=bracket_id)
    team_submission_points: dict[Any, int] = defaultdict(int)
    for row in dedupe_qs.values("participant__team_id", "challenge_id").annotate(best=Max("points_awarded")):
        team_submission_points[row["participant__team_id"]] += row["best"]

    # Combine deduped submission points with awards, then rank in Python (the
    # DB ordering used the flat submission_score annotation we removed). Ties
    # break on earliest last solve, nulls last — matching the materialized path.
    _MIN_AWARE = datetime.min.replace(tzinfo=UTC)
    teams = list(teams_qs)
    for team in teams:
        team.computed_score = team_submission_points.get(team.id, 0) + team.award_points
    teams.sort(key=lambda t: (-t.computed_score, t.last_solve_time is None, t.last_solve_time or _MIN_AWARE))

    if limit:
        teams = teams[:limit]

    return _build_team_scoreboard_rows(teams)


def get_participant_rank(participant_id: UUID) -> int | None:
    """Get the live event rank of a specific participant (1-indexed).

    Computed as ``1 + (number of eligible competitors ranking above)`` against
    the materialized columns, instead of rebuilding the whole scoreboard. Uses
    competition ranking (ties share the lower rank), matching the scoreboard's
    Python ranking exactly. Returns None when the participant does not exist or
    is not eligible (and so does not appear on the board).

    Args:
        participant_id: UUID of the participant.

    Returns:
        Rank as integer (1-indexed), or None.
    """
    # One query resolves existence AND eligibility: a missing or ineligible
    # participant does not appear on the board, so both return None (matching the
    # prior get_scoreboard-based behavior) without a second eligibility lookup.
    participant = (
        CTFParticipant.objects.filter(eligible_participant_q(), pk=participant_id)
        .only("event_id", "cached_score", "last_solve_at")
        .first()
    )
    if participant is None:
        return None

    my_score = participant.cached_score
    my_last = participant.last_solve_at or _RANK_NULL_LAST

    ahead = (
        CTFParticipant.objects.filter(eligible_participant_q(), event_id=participant.event_id)
        .annotate(eff_last=Coalesce("last_solve_at", Value(_RANK_NULL_LAST, output_field=DateTimeField())))
        .filter(Q(cached_score__gt=my_score) | Q(cached_score=my_score, eff_last__lt=my_last))
        .count()
    )
    return ahead + 1
