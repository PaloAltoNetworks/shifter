"""CTF statistics and timeline read paths.

Challenge statistics, per-participant score timeline, and event statistics.
These read authoritative ``CTFSubmission`` / ``CTFAward`` rows directly; they are
not on the high-frequency scoreboard-poll / submit path, so they are not
materialized.
"""

from __future__ import annotations

import logging
import statistics
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import Sum
from django.db.models.functions import Coalesce

from ctf.models import CTFAward, CTFParticipant, CTFSubmission
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


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
    solve_count = correct.count()
    participant_count = CTFParticipant.objects.filter(event_id=challenge.event_id).count()

    first_blood = correct.order_by("submitted_at").first()

    return {
        "challenge_id": str(challenge_id),
        "total_attempts": submissions.count(),
        "solve_count": solve_count,
        "first_blood": {
            "participant_name": first_blood.participant.name,
            "time": first_blood.submitted_at.isoformat(),
        }
        if first_blood
        else None,
        "solve_rate": solve_count / participant_count if participant_count else 0,
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

    # Late import via the package so a patched ``ctf.services.scoring.get_scoreboard``
    # is honoured (test seam preserved across the package split).
    from ctf.services.scoring import get_scoreboard

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
