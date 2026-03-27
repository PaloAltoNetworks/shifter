"""CTF Submission service.

Provides business logic for flag submission and hint usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFParticipant, CTFSubmission
from ctf.services.challenge import verify_flag

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _count_attempts_in_current_window(
    submissions_qs: QuerySet[CTFSubmission],
    cooldown_seconds: int,
) -> int:
    """Count submissions in the current timeout window.

    Walks backwards through submissions (newest first). Any gap >= cooldown
    between consecutive submissions marks a window reset — only submissions
    after the most recent such gap count toward the current window.
    """
    timestamps = list(submissions_qs.order_by("-submitted_at").values_list("submitted_at", flat=True))
    if not timestamps:
        return 0

    # Also check gap from now to most recent submission
    elapsed_since_last = (timezone.now() - timestamps[0]).total_seconds()
    if elapsed_since_last >= cooldown_seconds:
        return 0  # window has reset

    count = 1  # the most recent submission
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i] - timestamps[i + 1]).total_seconds()
        if gap >= cooldown_seconds:
            break  # found a reset boundary
        count += 1

    return count


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
    all_submissions = CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
    )
    total_attempt_count = all_submissions.count()

    if challenge.max_attempts > 0 and event.attempt_limit_mode == "timeout":
        # Timeout mode: count only submissions in the current window.
        # A gap >= cooldown between submissions resets the window.
        attempt_cooldown = event.attempt_limit_cooldown_seconds
        attempt_count = _count_attempts_in_current_window(all_submissions, attempt_cooldown)

        if attempt_count >= challenge.max_attempts:
            last_submission_time = (
                all_submissions.order_by("-submitted_at").values_list("submitted_at", flat=True).first()
            )
            if last_submission_time is None:
                # Defensive: should be unreachable since attempt_count > 0
                attempt_count = 0
            else:
                elapsed = (timezone.now() - last_submission_time).total_seconds()
                retry_after = int(attempt_cooldown - elapsed) + 1
                raise CTFRateLimitError(
                    f"Maximum attempts ({challenge.max_attempts}) reached. Try again in {retry_after} seconds.",
                    details={
                        "challenge_id": str(challenge_id),
                        "max_attempts": challenge.max_attempts,
                        "attempts_used": attempt_count,
                        "retry_after_seconds": retry_after,
                        "attempt_limit_mode": "timeout",
                    },
                )
    else:
        attempt_count = total_attempt_count
        if challenge.max_attempts > 0 and attempt_count >= challenge.max_attempts:
            # Lockout mode — permanent block
            raise CTFRateLimitError(
                f"Maximum attempts ({challenge.max_attempts}) exceeded",
                details={
                    "challenge_id": str(challenge_id),
                    "max_attempts": challenge.max_attempts,
                    "attempts_used": total_attempt_count,
                    "attempt_limit_mode": "lockout",
                },
            )

    # Check submission rate limit (time-based cooldown)
    cooldown = participant.event.submission_cooldown_seconds
    if cooldown > 0:
        last_submission_time = (
            CTFSubmission.objects.filter(
                participant=participant,
                challenge=challenge,
            )
            .order_by("-submitted_at")
            .values_list("submitted_at", flat=True)
            .first()
        )
        if last_submission_time is not None:
            elapsed = (timezone.now() - last_submission_time).total_seconds()
            if elapsed < cooldown:
                retry_after = int(cooldown - elapsed) + 1
                raise CTFRateLimitError(
                    f"Please wait {retry_after} seconds before submitting again",
                    details={
                        "challenge_id": str(challenge_id),
                        "retry_after_seconds": retry_after,
                        "cooldown_seconds": cooldown,
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
