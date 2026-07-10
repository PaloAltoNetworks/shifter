"""Materialized leaderboard maintenance (issue #850).

Recompute the denormalized ``cached_*`` columns on ``CTFParticipant`` and
``CTFTeam`` from the authoritative ``CTFSubmission`` / ``CTFAward`` rows.

These helpers are the single source of truth for derived leaderboard state.
They are called:

- incrementally from the submission / award / participant / team services
  after an authoritative write commits, so the live scoreboard and rank reads
  stay correct without recomputing the whole board; and
- in bulk by the ``ctf_recompute_leaderboard`` management command, on event
  status transitions, and by the backfill data migration, so the derived state
  is always rebuildable from source (per the issue #850 preflight guardrail).

The per-participant / per-team aggregates here intentionally mirror the live
(no-freeze) read paths in ``_read.py`` so a materialized read equals what an
on-demand recompute would have produced.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Count, Max, Sum
from django.db.models.functions import Coalesce

from ctf.models import CTFAward, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.participant import eligible_participant_q

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def recompute_participant_score(participant_id: UUID) -> None:
    """Rebuild a participant's materialized score columns from authoritative rows.

    Score is the sum of points from the participant's correct submissions plus
    their awards; solve count is the number of correct submissions; last-solve
    time is the most recent correct submission. Mirrors the per-participant
    annotations in ``get_scoreboard`` (no freeze).

    Uses ``QuerySet.update`` rather than ``Model.save`` so the write is a single
    atomic UPDATE that does not run the participant ``save()`` side effects
    (invite-token generation) or touch unrelated fields.

    The lock-then-aggregate-then-write runs inside a transaction with a row lock
    on the participant, so concurrent recomputes of the same participant
    serialize and cannot lose an update. ``select_for_update`` is a no-op on
    SQLite (the test backend) and a real row lock on PostgreSQL (production);
    nested inside a caller's atomic block the lock is held until the outermost
    transaction commits.
    """
    with transaction.atomic():
        if CTFParticipant.objects.select_for_update().filter(pk=participant_id).first() is None:
            return
        submissions = CTFSubmission.objects.filter(
            participant_id=participant_id,
            is_correct=True,
        ).aggregate(
            points=Coalesce(Sum("points_awarded"), 0),
            solves=Count("id"),
            last_solve=Max("submitted_at"),
        )
        award_points = CTFAward.objects.filter(participant_id=participant_id).aggregate(
            points=Coalesce(Sum("points"), 0),
        )["points"]

        CTFParticipant.objects.filter(pk=participant_id).update(
            cached_score=submissions["points"] + award_points,
            cached_solve_count=submissions["solves"],
            last_solve_at=submissions["last_solve"],
        )


def recompute_team_score(team_id: UUID | None) -> None:
    """Rebuild a team's materialized score columns from eligible members' rows.

    Score, distinct-challenge solve count, last-solve time, and member count are
    computed over the team's eligible (registered, non-disqualified) members,
    mirroring the per-team aggregation in ``get_team_scoreboard`` (no freeze, no
    bracket). A ``None`` team id is a no-op so callers can pass
    ``participant.team_id`` unconditionally.

    Locks the team row first (see ``recompute_participant_score``) so concurrent
    recomputes of the same team (e.g. two members solving at once) serialize.
    Always lock participant before team across operations to keep a consistent
    lock order.
    """
    if team_id is None:
        return

    with transaction.atomic():
        if CTFTeam.objects.select_for_update().filter(pk=team_id).first() is None:
            return

        member_ids = list(
            CTFParticipant.objects.filter(team_id=team_id).filter(eligible_participant_q()).values_list("id", flat=True)
        )

        if member_ids:
            correct = CTFSubmission.objects.filter(
                participant_id__in=member_ids,
                is_correct=True,
            )
            # Dedupe by challenge: a challenge solved by more than one teammate
            # counts once for the team, at its best (max) points. A plain
            # Sum("points_awarded") double-counted shared solves (#1138). Summed
            # in Python over the per-challenge maxes to avoid a nested DB
            # aggregate; the distinct-challenge set is small.
            per_challenge = list(
                correct.values("challenge_id").annotate(best=Max("points_awarded")).values_list("best", flat=True)
            )
            challenge_points = sum(per_challenge)
            last_solve = correct.aggregate(last_solve=Max("submitted_at"))["last_solve"]
            award_points = CTFAward.objects.filter(participant_id__in=member_ids).aggregate(
                points=Coalesce(Sum("points"), 0),
            )["points"]
            score = challenge_points + award_points
            solve_count = len(per_challenge)
        else:
            score = 0
            solve_count = 0
            last_solve = None

        CTFTeam.objects.filter(pk=team_id).update(
            cached_score=score,
            cached_solve_count=solve_count,
            last_solve_at=last_solve,
            cached_member_count=len(member_ids),
        )


def recompute_event_leaderboard(event_id: UUID | None = None) -> tuple[int, int]:
    """Rebuild materialized columns for every participant and team.

    Optionally scoped to a single event. Returns ``(participants, teams)``
    rebuilt. This is the rebuild path that makes the derived state recoverable
    from the authoritative rows at any time.
    """
    participants = CTFParticipant.objects.all()
    teams = CTFTeam.objects.all()
    if event_id is not None:
        participants = participants.filter(event_id=event_id)
        teams = teams.filter(event_id=event_id)

    # Materialize the id lists before the loop: each recompute opens its own
    # transaction (for the row lock), which must not run inside an open
    # server-side cursor from `.iterator()`.
    participant_ids = list(participants.values_list("id", flat=True))
    team_ids = list(teams.values_list("id", flat=True))

    for participant_id in participant_ids:
        recompute_participant_score(participant_id)

    for team_id in team_ids:
        recompute_team_score(team_id)

    participant_count = len(participant_ids)
    team_count = len(team_ids)

    logger.info(
        "Recomputed CTF leaderboard: %d participants, %d teams (event=%s)",
        participant_count,
        team_count,
        event_id if event_id is not None else "all",
    )
    return participant_count, team_count
