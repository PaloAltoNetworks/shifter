"""CTF challenge read path: single lookups and filtered listings."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from ctf.enums import EventCapability
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFChallenge, CTFChallengePrerequisite, CTFEvent
from ctf.services.authorization import assert_event_capability as _assert_event_capability


def get_challenge(challenge_id: UUID) -> CTFChallenge:
    """Get a challenge by ID.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        The CTFChallenge instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
    """
    try:
        return CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None


def get_available_challenges(
    event_id: UUID,
    include_unreleased: bool = False,
    participant_id: UUID | None = None,
) -> QuerySet[CTFChallenge]:
    """Get challenges available for an event.

    Args:
        event_id: UUID of the event.
        include_unreleased: If True, include challenges with future release times.
        participant_id: If provided, exclude challenges with unmet prerequisites.

    Returns:
        QuerySet of CTFChallenge instances.
    """
    from django.db.models import Q

    qs = CTFChallenge.objects.filter(event_id=event_id)

    if not include_unreleased:
        now = timezone.now()
        # Exclude hidden challenges and those not yet released
        qs = qs.exclude(visibility="hidden")
        qs = qs.filter(Q(release_time__isnull=True) | Q(release_time__lte=now))

    if participant_id is not None:
        from ctf.models import CTFSubmission

        solved_ids = set(
            CTFSubmission.objects.filter(
                participant_id=participant_id,
                is_correct=True,
            ).values_list("challenge_id", flat=True)
        )
        # Exclude challenges that have active prerequisites not yet solved
        challenges_with_unmet = set()
        prereqs = CTFChallengePrerequisite.objects.filter(
            challenge__event_id=event_id,
        ).values_list("challenge_id", "required_challenge_id")
        for challenge_id, required_id in prereqs:
            if required_id not in solved_ids:
                challenges_with_unmet.add(challenge_id)

        if challenges_with_unmet:
            qs = qs.exclude(id__in=challenges_with_unmet)

    return qs.order_by("category", "order", "name")


def list_challenges_for_event(event_id: UUID, *, actor_id: int) -> QuerySet[CTFChallenge]:
    """List all challenges for an event (admin/organizer view).

    Args:
        event_id: UUID of the event.
        actor_id: User pk of the caller. Required (issue #765 DiD): the
            service refuses unless `actor_id == event.created_by_id`.

    Returns:
        QuerySet of CTFChallenge instances.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFPermissionError: If actor does not own the event.
    """
    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    _assert_event_capability(actor_id, event, EventCapability.CHALLENGES)

    return CTFChallenge.objects.filter(event_id=event_id).order_by("category", "order", "name")
