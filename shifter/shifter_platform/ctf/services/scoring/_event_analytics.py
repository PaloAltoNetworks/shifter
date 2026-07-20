"""Event-level analytics for the organizer dashboard (CTF-1302).

Read-only aggregates over authoritative submission/hint rows; available at
any point during or after the event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Count, Q

from ctf.models import CTFChallenge, CTFEvent, CTFParticipant, CTFSubmission
from ctf.services.participant import ranked_participant_q

if TYPE_CHECKING:
    from uuid import UUID

_HISTOGRAM_BUCKETS = 10


def get_event_analytics(event_id: UUID) -> dict[str, Any]:
    """Return dashboard aggregates: score histogram, solve timeline, challenge and engagement stats."""
    from ctf.exceptions import CTFNotFoundError

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(f"Event {event_id} not found", details={"event_id": str(event_id)}) from None

    ranked = CTFParticipant.objects.filter(ranked_participant_q(), event=event)
    scores = sorted(ranked.values_list("cached_score", flat=True))

    return {
        "event_id": str(event.pk),
        "score_distribution": _score_histogram(scores),
        "solve_timeline": _solve_timeline(event),
        "challenges": _challenge_analysis(event, ranked.count()),
        "engagement": _engagement(event),
    }


def _score_histogram(scores: list[int]) -> list[dict[str, int]]:
    """Bucket ranked participants' scores into a fixed-width histogram."""
    if not scores:
        return []
    top = max(scores[-1], 1)
    width = max(1, -(-top // _HISTOGRAM_BUCKETS))
    buckets = [
        {"from": index * width, "to": (index + 1) * width - 1, "count": 0} for index in range(_HISTOGRAM_BUCKETS)
    ]
    for score in scores:
        buckets[min(score // width, _HISTOGRAM_BUCKETS - 1)]["count"] += 1
    return buckets


def _solve_timeline(event: CTFEvent) -> list[dict[str, Any]]:
    """Correct solves grouped per hour across the event."""
    from django.db.models.functions import TruncHour

    rows = (
        CTFSubmission.objects.filter(participant__event=event, is_correct=True)
        .annotate(hour=TruncHour("submitted_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )
    return [{"hour": row["hour"].isoformat() if row["hour"] else None, "solves": row["count"]} for row in rows]


def _challenge_analysis(event: CTFEvent, ranked_count: int) -> list[dict[str, Any]]:
    """Per-challenge solve rate versus point value (difficulty calibration)."""
    challenges = (
        CTFChallenge.objects.filter(event=event, deleted_at__isnull=True)
        .annotate(
            solves=Count("submissions", filter=Q(submissions__is_correct=True), distinct=True),
            attempts=Count("submissions", distinct=True),
        )
        .order_by("order", "name")
    )
    return [
        {
            "name": c.name,
            "points": c.points,
            "solves": c.solves,
            "attempts": c.attempts,
            "solve_rate": round(c.solves / ranked_count, 3) if ranked_count else 0.0,
        }
        for c in challenges
    ]


def _engagement(event: CTFEvent) -> dict[str, Any]:
    """Cohort engagement: activity, breadth of attempts, hint appetite."""
    from ctf.models import CTFHintUsage

    participants = CTFParticipant.objects.filter(event=event, registered_at__isnull=False)
    total = participants.count()
    active = participants.filter(last_active_at__isnull=False).count()
    attempted = (
        CTFSubmission.objects.filter(participant__event=event)
        .values("participant_id")
        .annotate(challenges=Count("challenge_id", distinct=True))
    )
    attempted_counts = [row["challenges"] for row in attempted]
    return {
        "registered": total,
        "active": active,
        "with_submissions": len(attempted_counts),
        "avg_challenges_attempted": round(sum(attempted_counts) / len(attempted_counts), 2)
        if attempted_counts
        else 0.0,
        "hints_used": CTFHintUsage.objects.filter(participant__event=event).count(),
    }
