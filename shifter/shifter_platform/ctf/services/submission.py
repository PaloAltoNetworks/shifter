"""CTF Submission service.

Provides business logic for flag submission and scoring.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengeRating, CTFParticipant, CTFSubmission
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


def _check_attempt_limit_or_raise(all_submissions, event, challenge, challenge_id) -> int:
    """Enforce per-challenge max-attempts (timeout or lockout mode); return the count to record.

    Returns the attempt count that the eventual `CTFSubmission` row should be
    one-based against. Raises `CTFRateLimitError` if the participant is over
    the cap. `challenge.max_attempts <= 0` disables the check.
    """
    total_attempt_count = all_submissions.count()
    if not (challenge.max_attempts > 0 and event.attempt_limit_mode == "timeout"):
        if challenge.max_attempts > 0 and total_attempt_count >= challenge.max_attempts:
            raise CTFRateLimitError(
                f"Maximum attempts ({challenge.max_attempts}) exceeded",
                details={
                    "challenge_id": str(challenge_id),
                    "max_attempts": challenge.max_attempts,
                    "attempts_used": total_attempt_count,
                    "attempt_limit_mode": "lockout",
                },
            )
        return total_attempt_count

    # Timeout mode: count only submissions in the current window.
    attempt_cooldown = event.attempt_limit_cooldown_seconds
    attempt_count = _count_attempts_in_current_window(all_submissions, attempt_cooldown)
    if attempt_count < challenge.max_attempts:
        return attempt_count

    last_submission_time = all_submissions.order_by("-submitted_at").values_list("submitted_at", flat=True).first()
    if last_submission_time is None:
        # Defensive: should be unreachable since attempt_count > 0
        return 0
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


def _check_submission_cooldown_or_raise(participant, challenge, challenge_id) -> None:
    """Enforce the time-based submission cooldown; raise `CTFRateLimitError` if active."""
    cooldown = participant.event.submission_cooldown_seconds
    if cooldown <= 0:
        return
    last_submission_time = (
        CTFSubmission.objects.filter(participant=participant, challenge=challenge)
        .order_by("-submitted_at")
        .values_list("submitted_at", flat=True)
        .first()
    )
    if last_submission_time is None:
        return
    elapsed = (timezone.now() - last_submission_time).total_seconds()
    if elapsed >= cooldown:
        return
    retry_after = int(cooldown - elapsed) + 1
    retry_at = last_submission_time + timedelta(seconds=cooldown)
    raise CTFRateLimitError(
        f"Please wait {retry_after} seconds before submitting again (retry at {retry_at.isoformat()})",
        details={
            "challenge_id": str(challenge_id),
            "retry_after_seconds": retry_after,
            "retry_at": retry_at.isoformat(),
            "cooldown_seconds": cooldown,
        },
    )


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

    # Issue #769: shared participant→challenge availability policy. Same
    # contract as use_hint(), so hints can never be easier to obtain than
    # flag submission. Covers event match, ACTIVE status, competition
    # window (CTF-702), visibility, release state, and prerequisites.
    from ctf.services.challenge import assert_challenge_available_for_participant

    assert_challenge_available_for_participant(participant, challenge)

    event = participant.event

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

    all_submissions = CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
    )
    attempt_count = _check_attempt_limit_or_raise(all_submissions, event, challenge, challenge_id)
    _check_submission_cooldown_or_raise(participant, challenge, challenge_id)

    # Calculate hint penalty
    from ctf.services.hint import get_total_hint_penalty

    total_hint_penalty = get_total_hint_penalty(participant.id, challenge.id)

    # Verify flag
    is_correct = verify_flag(challenge, submitted_flag.strip())

    # Calculate points
    points = 0
    if is_correct:
        points = challenge.calculate_points_with_penalty(total_hint_penalty)
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


def rate_challenge(
    participant_id: UUID,
    challenge_id: UUID,
    value: int,
) -> CTFChallengeRating:
    """Rate a challenge (1-5). Participant must have solved the challenge.

    Creates a new rating or updates existing one (upsert).

    Args:
        participant_id: UUID of the participant.
        challenge_id: UUID of the challenge.
        value: Rating value (1-5).

    Returns:
        The CTFChallengeRating instance.

    Raises:
        CTFNotFoundError: If participant or challenge doesn't exist.
        CTFValidationError: If participant hasn't solved the challenge or value is invalid.
    """
    if not (1 <= value <= 5):
        raise CTFValidationError(
            "Rating must be between 1 and 5",
            details={"value": value},
        )

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    # Codex review (#765 cycle 6): an internal caller passing a raw
    # participant_id for an INVITED or DISQUALIFIED row would otherwise
    # bypass the access predicate the views apply via
    # `is_active_participant`. Mirror that here.
    from ctf.services.participant import _PLAYING_PARTICIPANT_STATUSES

    if participant.registered_at is None or participant.status not in _PLAYING_PARTICIPANT_STATUSES:
        from ctf.exceptions import CTFStateError as _CTFStateError

        raise _CTFStateError(
            "Participant is not eligible",
            details={"participant_id": str(participant.id), "status": participant.status},
        )

    try:
        challenge = CTFChallenge.objects.get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    # Validate participant and challenge belong to the same event
    if challenge.event_id != participant.event_id:
        raise CTFValidationError(
            "Challenge does not belong to participant's event",
            details={
                "participant_event": str(participant.event_id),
                "challenge_event": str(challenge.event_id),
            },
        )

    # Check event has ratings enabled
    if challenge.event.rating_visibility == "disabled":
        raise CTFValidationError(
            "Ratings are disabled for this event",
            details={"challenge_id": str(challenge_id)},
        )

    # Check participant solved the challenge
    solved = CTFSubmission.objects.filter(
        participant=participant,
        challenge=challenge,
        is_correct=True,
    ).exists()

    if not solved:
        raise CTFValidationError(
            "You must solve a challenge before rating it",
            details={"challenge_id": str(challenge_id)},
        )

    # Upsert rating
    rating, _ = CTFChallengeRating.objects.update_or_create(
        participant=participant,
        challenge=challenge,
        defaults={"value": value},
    )

    logger.info(
        "Challenge rated: participant=%s, challenge=%s, value=%d",
        participant_id,
        challenge_id,
        value,
    )

    return rating


def get_challenge_rating(challenge_id: UUID) -> dict[str, float | int | None]:
    """Get average rating and count for a challenge.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        Dict with 'average' (float or None) and 'count' (int).
    """
    from django.db.models import Avg, Count

    result = CTFChallengeRating.objects.filter(challenge_id=challenge_id).aggregate(
        average=Avg("value"),
        count=Count("id"),
    )
    return {
        "average": round(result["average"], 1) if result["average"] is not None else None,
        "count": result["count"],
    }
