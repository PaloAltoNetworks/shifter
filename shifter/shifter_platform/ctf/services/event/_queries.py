"""CTF Event read-model queries: authority-aware discovery and per-event statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from ctf.models import CTFEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def resolve_administrable_events(
    user: User,
    *,
    status: str | None = None,
) -> QuerySet[CTFEvent]:
    """Return the events ``user`` may administer, scoped by their authority (ADR-052-R3).

    This is the one authority-aware discovery query; ``get_organizer_events`` and
    ``ctf.services.event._crud.list_events_for_organizer`` both delegate here so a
    single policy governs the list. Discovery never widens per-object mutation
    authority, which the service resolver re-checks per operation.

    - Platform administrator (active, non-temporary superuser): every live event
      through the default manager, so archived events are included but
      soft-deleted tombstones are excluded (tombstones stay recovery/destruction
      only).
    - Ordinary user: the deduplicated union of events they own and events where
      they hold a live ``CTFEventStaff`` assignment.

    The owner join is eager and ordering is deterministic (``-event_start`` then
    ``id``) so paginated results are stable and free of an N+1 owner lookup.
    """
    from ctf.services.authorization import is_ctf_platform_admin

    if is_ctf_platform_admin(user):
        queryset = CTFEvent.objects.all()
    else:
        queryset = CTFEvent.objects.filter(
            Q(created_by=user) | Q(staff__user=user, staff__deleted_at__isnull=True)
        ).distinct()

    if status:
        queryset = queryset.filter(status=status)

    return queryset.select_related("created_by").order_by("-event_start", "id")


def get_organizer_events(
    user: User,
    *,
    status: str | None = None,
) -> QuerySet[CTFEvent]:
    """Authority-aware event discovery for the organizer surface.

    Thin alias over :func:`resolve_administrable_events`; retained as a stable
    import for existing callers. A platform administrator sees all live events; an
    ordinary organizer sees owned plus live staff-assigned events (ADR-052-R3).
    """
    return resolve_administrable_events(user, status=status)


def get_event_stats(event: CTFEvent) -> dict[str, int]:
    """Get statistics for an event.

    Args:
        event: The event to get stats for.

    Returns:
        Dictionary with event statistics.
    """
    from django.db.models import Sum

    from ctf.enums import ParticipantStatus
    from ctf.models import CTFSubmission

    stats = {
        "participant_count": event.participants.count(),
        "registered_count": event.participants.filter(
            status__in=[
                ParticipantStatus.REGISTERED.value,
                ParticipantStatus.ACTIVE.value,
                ParticipantStatus.COMPLETED.value,
            ]
        ).count(),
        "challenge_count": event.challenges.count(),
        "team_count": event.teams.count() if event.team_mode else 0,
        "total_submissions": CTFSubmission.objects.filter(participant__event=event).count(),
        "correct_submissions": CTFSubmission.objects.filter(
            participant__event=event,
            is_correct=True,
        ).count(),
    }

    # Calculate total possible points
    points_result = event.challenges.aggregate(total=Sum("points"))
    stats["total_points"] = points_result["total"] or 0

    return stats
