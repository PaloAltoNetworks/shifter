"""CTF Scoring service.

Provides business logic for score calculation and leaderboards.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce

from ctf.enums import ParticipantStatus
from ctf.models import CTFParticipant, CTFSubmission, CTFTeam

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)


def calculate_score(participant_id: UUID) -> int:
    """Calculate total score for a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Total score as integer.
    """
    result = CTFSubmission.objects.filter(
        participant_id=participant_id,
        is_correct=True,
    ).aggregate(total=Coalesce(Sum("points_awarded"), 0))

    return result["total"]


def get_scoreboard(event_id: UUID, limit: int | None = None) -> list[dict[str, Any]]:
    """Get scoreboard for an event.

    Returns ranked list of participants with scores.
    Tie-breaker: earlier last solve time wins.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.

    Returns:
        List of dicts with rank, participant info, score, and solve count.
    """
    logger.debug("Getting scoreboard for event %s", event_id)

    participants = (
        CTFParticipant.objects.filter(
            event_id=event_id,
            status__in=[
                ParticipantStatus.ACTIVE.value,
                ParticipantStatus.REGISTERED.value,
                ParticipantStatus.COMPLETED.value,
            ],
        )
        .annotate(
            total_score=Coalesce(
                Sum(
                    "submissions__points_awarded",
                    filter=Q(submissions__is_correct=True),
                ),
                0,
            ),
            solve_count=Count(
                "submissions",
                filter=Q(submissions__is_correct=True),
            ),
            last_solve_time=Max(
                "submissions__submitted_at",
                filter=Q(submissions__is_correct=True),
            ),
        )
        .order_by("-total_score", "last_solve_time")
        .select_related("team")
    )

    if limit:
        participants = participants[:limit]

    scoreboard: list[dict[str, Any]] = []
    current_rank = 0
    last_score = None
    last_time = None

    for i, p in enumerate(participants):
        # Calculate rank (handle ties)
        if p.total_score != last_score or p.last_solve_time != last_time:
            current_rank = i + 1

        scoreboard.append({
            "rank": current_rank,
            "participant_id": str(p.id),
            "name": p.name,
            "team_name": p.team.name if p.team else None,
            "score": p.total_score,
            "solve_count": p.solve_count,
            "last_solve": p.last_solve_time.isoformat() if p.last_solve_time else None,
        })

        last_score = p.total_score
        last_time = p.last_solve_time

    return scoreboard


def get_team_scoreboard(event_id: UUID, limit: int | None = None) -> list[dict[str, Any]]:
    """Get team scoreboard for an event.

    Aggregates scores across team members.
    Tie-breaker: earlier last solve time wins.

    Args:
        event_id: UUID of the event.
        limit: Optional limit on number of results.

    Returns:
        List of dicts with rank, team info, score, and member count.
    """
    logger.debug("Getting team scoreboard for event %s", event_id)

    teams = (
        CTFTeam.objects.filter(event_id=event_id)
        .annotate(
            total_score=Coalesce(
                Sum(
                    "members__submissions__points_awarded",
                    filter=Q(members__submissions__is_correct=True),
                ),
                0,
            ),
            solve_count=Count(
                "members__submissions",
                filter=Q(members__submissions__is_correct=True),
            ),
            member_count=Count("members", distinct=True),
            last_solve_time=Max(
                "members__submissions__submitted_at",
                filter=Q(members__submissions__is_correct=True),
            ),
        )
        .order_by("-total_score", "last_solve_time")
    )

    if limit:
        teams = teams[:limit]

    scoreboard: list[dict[str, Any]] = []
    current_rank = 0
    last_score = None
    last_time = None

    for i, t in enumerate(teams):
        # Calculate rank (handle ties)
        if t.total_score != last_score or t.last_solve_time != last_time:
            current_rank = i + 1

        scoreboard.append({
            "rank": current_rank,
            "team_id": str(t.id),
            "name": t.name,
            "score": t.total_score,
            "solve_count": t.solve_count,
            "member_count": t.member_count,
            "last_solve": t.last_solve_time.isoformat() if t.last_solve_time else None,
        })

        last_score = t.total_score
        last_time = t.last_solve_time

    return scoreboard


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
        } if first_blood else None,
        "solve_rate": (
            correct.count() / submissions.values("participant").distinct().count()
            if submissions.exists()
            else 0
        ),
    }


def get_event_statistics(event_id: UUID) -> dict[str, Any]:
    """Get overall statistics for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with participant count, submission count, etc.
    """
    from ctf.models import CTFChallenge, CTFEvent

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        return {}

    participants = CTFParticipant.objects.filter(event=event)
    challenges = CTFChallenge.objects.filter(event=event)
    submissions = CTFSubmission.objects.filter(participant__event=event)

    return {
        "event_id": str(event_id),
        "participant_count": participants.count(),
        "active_participants": participants.filter(
            status__in=[ParticipantStatus.ACTIVE.value, ParticipantStatus.REGISTERED.value]
        ).count(),
        "challenge_count": challenges.count(),
        "total_submissions": submissions.count(),
        "correct_submissions": submissions.filter(is_correct=True).count(),
        "total_points_awarded": submissions.filter(is_correct=True).aggregate(
            total=Coalesce(Sum("points_awarded"), 0)
        )["total"],
    }
