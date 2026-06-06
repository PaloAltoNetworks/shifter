"""CTF Scoring service.

Provides business logic for score calculation and leaderboards.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import Count, F, Max, Q, Sum
from django.db.models.functions import Coalesce

from ctf.models import CTFAward, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.participant import eligible_participant_q
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


def calculate_score(participant_id: UUID) -> int:
    """Calculate total score for a participant (submissions + awards).

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

    Rows are the annotate()-augmented CTFParticipant instances from get_scoreboard;
    typed as Any because the score/solve aggregates are dynamic query annotations.
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

    Rows are the annotate()-augmented CTFTeam instances from get_team_scoreboard;
    typed as Any because the score/solve aggregates are dynamic query annotations.
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
    """Get scoreboard for an event.

    Returns ranked list of participants with scores.
    Tie-breaker: earlier last solve time wins.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.
        freeze_at: Optional freeze cutoff. When set, only submissions/awards
            before this time are counted.
        bracket_id: Optional bracket filter. When set, only participants in
            this bracket are included.

    Returns:
        List of dicts with rank, participant info, score, and solve count.
    """
    logger.debug("Getting scoreboard for event %s", event_id)

    # Codex review cycle 6 (mirrors the team-scoreboard cycle-5 fix):
    # annotating both `submissions` and `awards` on the same participant
    # queryset joined them in one SQL query, so a participant with both a
    # solve and an award produced a cartesian product that inflated both
    # scores and counts. Pre-aggregate via per-participant subqueries on
    # CTFSubmission and CTFAward instead.
    from django.db.models import IntegerField, OuterRef, Subquery

    submission_qs = CTFSubmission.objects.filter(
        is_correct=True,
        participant_id=OuterRef("pk"),
    )
    if freeze_at:
        submission_qs = submission_qs.filter(submitted_at__lt=freeze_at)

    award_qs = CTFAward.objects.filter(participant_id=OuterRef("pk"))
    if freeze_at:
        award_qs = award_qs.filter(created_at__lt=freeze_at)

    # Eligibility (status not disqualified + registration completed) is the
    # single shared predicate from `ctf.services.participant`. Codex review
    # cycle 3 caught the predicate divergence — keep the filter sourced
    # from one place so individual scoring, team scoring, and access
    # checks cannot drift apart.
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
        .order_by("-computed_score", "last_solve_time")
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
    """Get team scoreboard for an event.

    Aggregates scores across team members.
    Tie-breaker: earlier last solve time wins.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.
        freeze_at: Optional freeze cutoff. When set, only submissions/awards
            before this time are counted.
        bracket_id: Optional bracket filter. When set, only scores from
            team members in this bracket are counted.

    Returns:
        List of dicts with rank, team info, score, and member count.
    """
    logger.debug("Getting team scoreboard for event %s", event_id)

    # Codex review cycle 5 (and cycle 3): the previous implementation
    # joined `members__submissions` and `members__awards` in the SAME
    # aggregate query — so when a member had both a solve and an award,
    # the cartesian product multiplied each row, inflating both team
    # score and award points. Pre-aggregate submissions and awards as
    # SEPARATE per-team subqueries (each over its own join), then add
    # them in Python after the row-multiplication is gone.
    #
    # Eligibility (non-disqualified, registered) is applied inside each
    # subquery so disqualified members' solves and awards no longer leak
    # into team totals.
    from django.db.models import IntegerField, OuterRef, Subquery

    # `eligible_participant_q("members__")` for filters applied at the
    # CTFTeam.members relation; bare `eligible_participant_q()` for filters
    # applied directly on CTFParticipant subqueries.
    member_eligibility_via_team = eligible_participant_q("members__")

    # Submission stats per team (sum of points, distinct solved challenge
    # count, max submitted_at), via a CTFSubmission queryset filtered by
    # team membership through the participant join.
    submission_qs = CTFSubmission.objects.filter(
        is_correct=True,
        participant__team_id=OuterRef("pk"),
    ).filter(eligible_participant_q("participant__"))
    if freeze_at:
        submission_qs = submission_qs.filter(submitted_at__lt=freeze_at)
    if bracket_id is not None:
        submission_qs = submission_qs.filter(participant__bracket_id=bracket_id)

    # Award stats per team (sum of points), filtered the same way.
    award_qs = CTFAward.objects.filter(participant__team_id=OuterRef("pk")).filter(
        eligible_participant_q("participant__")
    )
    if freeze_at:
        award_qs = award_qs.filter(created_at__lt=freeze_at)
    if bracket_id is not None:
        award_qs = award_qs.filter(participant__bracket_id=bracket_id)

    # Member count per team (eligible-only). Applied on the CTFTeam.members
    # relation, so the predicate must be `members__`-prefixed.
    member_count_filter = member_eligibility_via_team
    if bracket_id is not None:
        member_count_filter &= Q(members__bracket_id=bracket_id)

    teams = (
        CTFTeam.objects.filter(event_id=event_id)
        .annotate(
            submission_score=Coalesce(
                Subquery(
                    submission_qs.order_by()
                    .values("participant__team_id")
                    .annotate(total=Coalesce(Sum("points_awarded"), 0))
                    .values("total"),
                    output_field=IntegerField(),
                ),
                0,
            ),
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
            computed_score=F("submission_score") + F("award_points"),
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
        )
        .order_by("-computed_score", "last_solve_time")
    )

    if limit:
        teams = teams[:limit]

    return _build_team_scoreboard_rows(teams)


def get_participant_rank(participant_id: UUID) -> int | None:
    """Get rank of a specific participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Rank as integer (1-indexed), or None if participant not found.
    """
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        return None

    # Get scoreboard and find participant
    scoreboard = get_scoreboard(participant.event_id)

    for entry in scoreboard:
        if entry["participant_id"] == str(participant_id):
            return entry["rank"]

    return None


def get_challenge_statistics(challenge_id: UUID) -> dict[str, Any]:
    """Get statistics for a challenge.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        Dict with solve count, attempt count, first blood, etc.
    """
    from ctf.models import CTFChallenge

    try:
        challenge = CTFChallenge.objects.get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        return {}

    submissions = CTFSubmission.objects.filter(challenge=challenge)
    correct = submissions.filter(is_correct=True)

    first_blood = correct.order_by("submitted_at").first()

    return {
        "challenge_id": str(challenge_id),
        "total_attempts": submissions.count(),
        "solve_count": correct.count(),
        "first_blood": {
            "participant_name": first_blood.participant.name,
            "time": first_blood.submitted_at.isoformat(),
        }
        if first_blood
        else None,
        "solve_rate": (
            correct.count() / distinct_participants
            if (distinct_participants := submissions.values("participant").distinct().count())
            else 0
        ),
    }


def get_score_timeline(participant_id: UUID) -> list[dict[str, Any]]:
    """Get cumulative score timeline for a participant.

    Returns a chronologically-ordered list of score events (solves and awards)
    with running cumulative totals, suitable for rendering a step chart.

    Args:
        participant_id: UUID of the participant.

    Returns:
        List of dicts with timestamp, points, cumulative score, label, and type.
        The first entry is always the event start with cumulative 0.
    """
    logger.debug("Getting score timeline for participant %s", safe_log_value(participant_id))

    participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    event_start = participant.event.event_start

    # Correct submissions ordered by time
    submissions = list(
        CTFSubmission.objects.filter(
            participant_id=participant_id,
            is_correct=True,
        )
        .values("submitted_at", "points_awarded", "challenge__name")
        .order_by("submitted_at")
    )

    # Awards ordered by time
    awards = list(
        CTFAward.objects.filter(
            participant_id=participant_id,
        )
        .values("created_at", "points", "reason")
        .order_by("created_at")
    )

    # Merge into unified event list
    events: list[tuple[datetime, int, str, str]] = []
    for s in submissions:
        events.append((s["submitted_at"], s["points_awarded"], s["challenge__name"] or "", "solve"))
    for a in awards:
        events.append((a["created_at"], a["points"], a["reason"] or "", "award"))

    events.sort(key=lambda e: e[0])

    # Fold pre-start events into the origin point's cumulative value
    pre_start_cumulative = 0
    post_start_events: list[tuple[datetime, int, str, str]] = []
    for ev in events:
        if ev[0] < event_start:
            pre_start_cumulative += ev[1]
        else:
            post_start_events.append(ev)

    # Build timeline with cumulative totals
    timeline: list[dict[str, Any]] = [
        {
            "timestamp": event_start.isoformat(),
            "points": pre_start_cumulative,
            "cumulative": pre_start_cumulative,
            "label": "Event start",
            "type": "start",
        }
    ]

    cumulative = pre_start_cumulative
    for ts, points, label, event_type in post_start_events:
        cumulative += points
        timeline.append(
            {
                "timestamp": ts.isoformat(),
                "points": points,
                "cumulative": cumulative,
                "label": label[:50] if len(label) > 50 else label,
                "type": event_type,
            }
        )

    return timeline


def get_event_statistics(event_id: UUID) -> dict[str, Any]:
    """Get overall statistics for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with participant count, submission count, score stats, etc.
    """
    from ctf.models import CTFChallenge, CTFEvent

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        return {}

    participants = CTFParticipant.objects.filter(event=event)
    challenges = CTFChallenge.objects.filter(event=event)
    submissions = CTFSubmission.objects.filter(participant__event=event)
    awards = CTFAward.objects.filter(event=event)

    total_submissions = submissions.count()
    correct_submissions = submissions.filter(is_correct=True).count()

    # Active participants: those with at least one submission
    active_participants = participants.filter(submissions__isnull=False).distinct().count()

    # Challenges with zero solves
    challenge_count = challenges.count()
    challenges_with_solves = submissions.filter(is_correct=True).values("challenge_id").distinct().count()
    challenges_with_zero_solves = challenge_count - challenges_with_solves

    # Compute per-participant scores for average/median
    scoreboard = get_scoreboard(event_id)
    scores = [entry["score"] for entry in scoreboard]
    average_score = round(statistics.mean(scores), 1) if scores else 0
    median_score = round(statistics.median(scores), 1) if scores else 0

    return {
        "event_id": str(event_id),
        "participant_count": participants.count(),
        "active_participants": active_participants,
        "challenge_count": challenge_count,
        "challenges_with_zero_solves": challenges_with_zero_solves,
        "total_submissions": total_submissions,
        "correct_submissions": correct_submissions,
        "incorrect_submissions": total_submissions - correct_submissions,
        "average_score": average_score,
        "median_score": median_score,
        "event_duration_hours": event.duration_hours,
        "total_points_awarded": submissions.filter(is_correct=True).aggregate(total=Coalesce(Sum("points_awarded"), 0))[
            "total"
        ],
        "total_awards": awards.count(),
    }
