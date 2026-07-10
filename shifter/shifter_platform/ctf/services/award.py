"""CTF Award service.

Provides business logic for organizer-granted awards (bonuses and deductions).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFAward, CTFEvent, CTFParticipant

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def grant_award(
    event_id: UUID,
    participant_id: UUID,
    points: int,
    reason: str,
    granted_by: User,
) -> CTFAward:
    """Grant an award (bonus or deduction) to a participant.

    Args:
        event_id: UUID of the event.
        participant_id: UUID of the participant.
        points: Points to add (positive) or deduct (negative).
        reason: Organizer's explanation for the award.
        granted_by: User granting the award.

    Returns:
        The created CTFAward instance.

    Raises:
        CTFNotFoundError: If event or participant doesn't exist.
        CTFValidationError: If participant doesn't belong to the event.
    """
    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(f"Event {event_id} not found.") from None

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(f"Participant {participant_id} not found.") from None

    if participant.event_id != event.pk:
        raise CTFValidationError("Participant does not belong to this event.")

    with transaction.atomic():
        award = CTFAward.objects.create(
            event=event,
            participant=participant,
            points=points,
            reason=reason,
            granted_by=granted_by,
        )
        # Maintain the materialized leaderboard (issue #850): an award changes
        # the participant's (and their team's) total score.
        from ctf.services.scoring import recompute_participant_score, recompute_team_score

        recompute_participant_score(participant.id)
        recompute_team_score(participant.team_id)

    logger.info(
        "Award granted: %+d points to participant %s in event %s by %s — %s",
        points,
        participant_id,
        event_id,
        granted_by,
        reason,
    )

    return award


def revoke_award(award_id: UUID) -> None:
    """Revoke (soft-delete) an award.

    Args:
        award_id: UUID of the award to revoke.

    Raises:
        CTFNotFoundError: If award doesn't exist.
    """
    try:
        award = CTFAward.objects.get(pk=award_id)
    except CTFAward.DoesNotExist:
        raise CTFNotFoundError(f"Award {award_id} not found.") from None

    with transaction.atomic():
        participant_id = award.participant_id
        team_id = award.participant.team_id
        award.delete(soft=True)
        # Maintain the materialized leaderboard (issue #850): revoking an award
        # removes its points from the participant's (and team's) total.
        from ctf.services.scoring import recompute_participant_score, recompute_team_score

        recompute_participant_score(participant_id)
        recompute_team_score(team_id)

    logger.info("Award revoked: %s", award_id)


def get_participant_awards(participant_id: UUID) -> QuerySet[CTFAward]:
    """Get all active awards for a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        QuerySet of CTFAward instances.
    """
    return CTFAward.objects.filter(participant_id=participant_id)


def get_event_awards(event_id: UUID) -> QuerySet[CTFAward]:
    """Get all active awards for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFAward instances.
    """
    return CTFAward.objects.filter(event_id=event_id)
