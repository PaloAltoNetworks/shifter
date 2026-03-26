"""CTF Submission service.

Provides business logic for flag submission and hint usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.enums import EventStatus
from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFParticipant, CTFSubmission
from ctf.services.challenge import verify_flag

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def submit_flag(
    participant_id: UUID,
    challenge_id: UUID,
    submitted_flag: str,
    ip_address: str | None = None,
) -> CTFSubmission:
    """Submit a flag for a challenge.

    Args:
        participant_id: UUID of the participant.
        challenge_id: UUID of the challenge.
        submitted_flag: The flag value submitted.
        ip_address: Client IP address for audit.

    Returns:
        The CTFSubmission instance.

    Raises:
        CTFNotFoundError: If participant or challenge doesn't exist.
        CTFStateError: If event is not active or challenge not released.
        CTFRateLimitError: If max attempts exceeded.
        CTFValidationError: If submission is invalid.
    """
    logger.info(
        "Flag submission: participant=%s, challenge=%s",
        participant_id,
        challenge_id,
    )

    # Get participant and challenge
    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    # Validate event state
    if challenge.event_id != participant.event_id:
        raise CTFValidationError(
            "Challenge does not belong to participant's event",
            details={
                "participant_event": str(participant.event_id),
                "challenge_event": str(challenge.event_id),
            },
        )

    event = participant.event
    if event.status != EventStatus.ACTIVE.value:
        raise CTFStateError(
            f"Event is not active (status: {event.status})",
            details={"event_id": str(event.id), "status": event.status},
        )

    # Check visibility state
    if challenge.visibility == "hidden":
        raise CTFStateError(
            "Challenge is not available",
            details={"challenge_id": str(challenge_id)},
        )
    if challenge.visibility == "locked":
        raise CTFStateError(
            "Challenge is locked",
            details={"challenge_id": str(challenge_id)},
        )

    # Check if challenge is released (time-based)
    if not challenge.is_released:
        raise CTFStateError(
            "Challenge has not been released yet",
            details={
                "challenge_id": str(challenge_id),
                "release_time": challenge.release_time.isoformat() if challenge.release_time else None,
            },
        )

    # Check prerequisites
    from ctf.services.challenge import check_prerequisites_met

    prereqs_met, unmet_challenges = check_prerequisites_met(challenge_id, participant_id)
    if not prereqs_met:
        unmet_names = [c.name for c in unmet_challenges]
        raise CTFStateError(
            f"Prerequisites not met. Complete first: {', '.join(unmet_names)}",
            details={
                "challenge_id": str(challenge_id),
                "unmet_prerequisites": [str(c.id) for c in unmet_challenges],
            },
        )

    # Check if already solved
    existing_correct = CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
        is_correct=True,
    ).exists()

    if existing_correct:
        raise CTFValidationError(
            "Challenge already solved",
            code="CTF_ALREADY_SOLVED",
            details={"challenge_id": str(challenge_id)},
        )

    # Check attempt limit
    attempt_count = CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
    ).count()

    if challenge.max_attempts > 0 and attempt_count >= challenge.max_attempts:
        raise CTFRateLimitError(
            f"Maximum attempts ({challenge.max_attempts}) exceeded",
            details={
                "challenge_id": str(challenge_id),
                "max_attempts": challenge.max_attempts,
                "attempts_used": attempt_count,
            },
        )

    # Check if hint was used
    hint_used = _check_hint_used(participant, challenge)

    # Verify flag
    is_correct = verify_flag(challenge, submitted_flag.strip())

    # Calculate points
    points = 0
    if is_correct:
        points = challenge.calculate_points_with_penalty(hint_used)
        logger.info(
            "Correct flag submitted: participant=%s, challenge=%s, points=%d",
            participant_id,
            challenge_id,
            points,
        )
    else:
        logger.debug(
            "Incorrect flag submitted: participant=%s, challenge=%s",
            participant_id,
            challenge_id,
        )

    # Create submission
    with transaction.atomic():
        submission = CTFSubmission.objects.create(
            participant=participant,
            challenge=challenge,
            submitted_flag=submitted_flag,
            is_correct=is_correct,
            points_awarded=points,
            hint_used=hint_used,
            attempt_number=attempt_count + 1,
            ip_address=ip_address,
        )

        # Update participant last active
        participant.update_last_active()

    return submission


def get_participant_submissions(
    participant_id: UUID,
    challenge_id: UUID | None = None,
) -> QuerySet[CTFSubmission]:
    """Get submissions for a participant.

    Args:
        participant_id: UUID of the participant.
        challenge_id: Optional challenge UUID to filter by.

    Returns:
        QuerySet of CTFSubmission instances.
    """
    qs = CTFSubmission.objects.filter(participant_id=participant_id)

    if challenge_id:
        qs = qs.filter(challenge_id=challenge_id)

    return qs.select_related("challenge").order_by("-submitted_at")


def use_hint(participant_id: UUID, challenge_id: UUID) -> str:
    """Mark hint as used and return hint text.

    Args:
        participant_id: UUID of the participant.
        challenge_id: UUID of the challenge.

    Returns:
        The hint text.

    Raises:
        CTFNotFoundError: If participant or challenge doesn't exist.
        CTFValidationError: If challenge has no hint.
    """
    logger.info(
        "Hint requested: participant=%s, challenge=%s",
        participant_id,
        challenge_id,
    )

    try:
        CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    try:
        challenge = CTFChallenge.objects.get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    if not challenge.hint:
        raise CTFValidationError(
            "Challenge has no hint available",
            details={"challenge_id": str(challenge_id)},
        )

    # Track hint usage (we'll check this during submission)
    # For now, we just log it - could add a HintUsage model later
    logger.info(
        "Hint used: participant=%s, challenge=%s, penalty=%d%%",
        participant_id,
        challenge_id,
        challenge.hint_penalty,
    )

    return challenge.hint


def _check_hint_used(participant: CTFParticipant, challenge: CTFChallenge) -> bool:
    """Check if participant has used hint for a challenge.

    Currently checks if there's any submission with hint_used=True.
    Could be enhanced with a dedicated HintUsage model.

    Args:
        participant: The participant.
        challenge: The challenge.

    Returns:
        True if hint was used, False otherwise.
    """
    # Check if any previous submission had hint_used=True
    return CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
        hint_used=True,
    ).exists()


def get_challenge_submissions(challenge_id: UUID) -> QuerySet[CTFSubmission]:
    """Get all submissions for a challenge (admin view).

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        QuerySet of CTFSubmission instances.
    """
    return (
        CTFSubmission.objects.filter(challenge_id=challenge_id).select_related("participant").order_by("-submitted_at")
    )


def get_correct_submissions(challenge_id: UUID) -> QuerySet[CTFSubmission]:
    """Get correct submissions for a challenge.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        QuerySet of correct CTFSubmission instances, ordered by time.
    """
    return (
        CTFSubmission.objects.filter(
            challenge_id=challenge_id,
            is_correct=True,
        )
        .select_related("participant")
        .order_by("submitted_at")
    )
