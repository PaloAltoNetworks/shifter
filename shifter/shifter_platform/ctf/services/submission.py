"""CTF Submission service.

Provides business logic for flag submission and scoring.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from ctf.enums import ScoringMode
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengeRating, CTFParticipant, CTFSubmission
from ctf.services.challenge import verify_flag
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Pacing gates split out for size (python:S104); same-transaction semantics.
from ctf.services.submission_gates import (  # noqa: E402
    _check_attempt_limit_or_raise,
    _check_submission_cooldown_or_raise,
)


def _load_submission_entities(participant_id: UUID, challenge_id: UUID) -> tuple[CTFParticipant, CTFChallenge]:
    """Load the submitting participant and target challenge or raise not-found."""
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
    return participant, challenge


def _verify_and_score(participant: CTFParticipant, challenge: CTFChallenge, submitted_flag: str) -> tuple[bool, int]:
    """Verify the flag and compute the awarded points without mutating state.

    Runs BEFORE the participant row lock is taken: a programmable/http flag
    check can be slow or make an outbound call, and we must not hold the lock
    across it.
    """
    from ctf.services.hint import get_total_hint_penalty
    from ctf.services.scoring import calculate_solve_points

    total_hint_penalty = get_total_hint_penalty(participant.id, challenge.id)
    is_correct = verify_flag(challenge, submitted_flag.strip())
    points = calculate_solve_points(participant.event, challenge, total_hint_penalty) if is_correct else 0
    if is_correct:
        logger.info(
            "Correct flag submitted: participant=%s, challenge=%s, points=%d",
            participant.id,
            safe_log_value(challenge.id),
            points,
        )
    else:
        logger.debug(
            "Incorrect flag submitted: participant=%s, challenge=%s",
            participant.id,
            safe_log_value(challenge.id),
        )
    return is_correct, points


def _record_submission_locked(
    participant: CTFParticipant,
    challenge: CTFChallenge,
    submitted_flag: str,
    *,
    is_correct: bool,
    points: int,
    ip_address: str | None,
) -> CTFSubmission:
    """Re-check gating under the participant lock, insert, and maintain scores.

    Serializes per participant so the already-solved / attempt-limit / cooldown
    checks and the INSERT cannot interleave with a concurrent submission for
    the same challenge (#1135, #1137). Without the lock two concurrent correct
    submissions both passed the already-solved check and double-scored, and
    concurrent wrong guesses both passed the max_attempts cap. The reads below
    run under select_for_update so they are authoritative; the partial unique
    constraint on (participant, challenge) WHERE is_correct is the DB backstop.
    """
    event = participant.event
    challenge_id = challenge.id
    dynamic_mode = event.scoring_mode == ScoringMode.DYNAMIC.value
    with transaction.atomic():
        CTFParticipant.objects.select_for_update().get(pk=participant.id)
        if dynamic_mode:
            # Serialize dynamic re-pricing per challenge (CTF-202): concurrent
            # solvers hold different participant locks, so the challenge row is
            # the shared lock that makes the solve count, the retroactive
            # points update, and the score recomputes one atomic step.
            CTFChallenge.objects.select_for_update().get(pk=challenge.pk)

        submissions = CTFSubmission.objects.filter(participant=participant, challenge=challenge)
        if submissions.filter(is_correct=True).exists():
            raise CTFValidationError(
                "Challenge already solved",
                code="CTF_ALREADY_SOLVED",
                details={"challenge_id": str(challenge_id)},
            )
        attempt_count = _check_attempt_limit_or_raise(submissions, event, challenge, challenge_id)
        _check_submission_cooldown_or_raise(participant, challenge, challenge_id)

        try:
            submission = CTFSubmission.objects.create(
                participant=participant,
                challenge=challenge,
                submitted_flag=submitted_flag,
                is_correct=is_correct,
                points_awarded=points,
                attempt_number=attempt_count + 1,
                ip_address=ip_address,
            )
        except IntegrityError as exc:
            # ctf_unique_correct_submission backstop: another correct submission
            # for this (participant, challenge) committed first.
            raise CTFValidationError(
                "Challenge already solved",
                code="CTF_ALREADY_SOLVED",
                details={"challenge_id": str(challenge_id)},
            ) from exc

        # Update participant last active
        participant.update_last_active()

        # Maintain the materialized leaderboard (issue #850) in the same
        # transaction as the authoritative write. Only a correct submission
        # changes score/solve-count/last-solve, so incorrect attempts stay
        # cheap (no recompute) — important under wrong-answer load.
        if is_correct and dynamic_mode:
            # Dynamic mode re-prices every correct solve (including this one)
            # and recomputes all affected participant/team scores (CTF-202).
            from ctf.services.scoring import apply_dynamic_decay

            apply_dynamic_decay(challenge)
            submission.refresh_from_db(fields=["points_awarded"])
        elif is_correct:
            from ctf.services.scoring import recompute_participant_score, recompute_team_score

            recompute_participant_score(participant.id)
            recompute_team_score(participant.team_id)

        if is_correct:
            first_blood = CTFSubmission.objects.filter(challenge=challenge, is_correct=True).count() == 1
        else:
            first_blood = False

    if is_correct:
        # CTF-802/CTF-1203: post-commit fanout so a bus or receiver hiccup can
        # never roll back the solve.
        from ctf.services.webhook import emit_webhook

        solve_data = {
            "challenge_id": str(challenge.pk),
            "challenge_name": challenge.name,
            "participant_id": str(participant.pk),
            "participant_name": participant.name,
            "points": submission.points_awarded,
        }
        emit_webhook(challenge.event, "flag_solve", solve_data)
        if first_blood:
            from ctf.services.notification import publish_event_notification

            publish_event_notification(
                challenge.event,
                "first_blood",
                {
                    "challenge_id": str(challenge.pk),
                    "challenge_name": challenge.name,
                    "participant_name": participant.name,
                },
            )
            emit_webhook(challenge.event, "first_blood", solve_data)

    return submission


def submit_flag(
    participant_id: UUID,
    challenge_id: UUID,
    submitted_flag: str,
    ip_address: str | None = None,
) -> CTFSubmission:
    """Submit a flag for a challenge.

    Orchestrates the explicit units: entity loading, the shared availability
    policy, lock-free verification/scoring, and the locked attempt recording.

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
        safe_log_value(challenge_id),
    )

    participant, challenge = _load_submission_entities(participant_id, challenge_id)

    # Compete gate before any flag verification work: refuses unregistered,
    # disqualified, and banned rows plus observers (CTF-604/605/609).
    from ctf.services.participant.queries import assert_participant_can_compete

    assert_participant_can_compete(participant)

    # Issue #769: shared participant→challenge availability policy. Same
    # contract as use_hint(), so hints can never be easier to obtain than
    # flag submission. Covers event match, ACTIVE status, competition
    # window (CTF-702), visibility, release state, and prerequisites.
    from ctf.services.challenge import assert_challenge_available_for_participant

    assert_challenge_available_for_participant(participant, challenge)

    is_correct, points = _verify_and_score(participant, challenge, submitted_flag)
    return _record_submission_locked(
        participant,
        challenge,
        submitted_flag,
        is_correct=is_correct,
        points=points,
        ip_address=ip_address,
    )


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


def get_participant_solve_history(
    participant_id: UUID,
    freeze_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Participant-safe correct-solve history for scoreboard row drill-down.

    Returns only *correct* submissions, newest first, projected to non-secret
    fields: challenge name, category, points awarded, and solve time. The
    submitted flag, attempt IP address, and incorrect-attempt details are
    deliberately excluded so this projection is safe to render on a
    participant-visible surface (issue #521 / CTF-401). Ranking and tie-break
    semantics (CTF-406) stay in ``ctf.services.scoring``; this is a display
    read only.

    Args:
        participant_id: UUID of the participant whose solves to return.
        freeze_at: When set, solves submitted at or after this cutoff are
            excluded so the drill-down matches the frozen scoreboard's
            visibility. Pass ``None`` (organizer view, or an unfrozen board)
            to return the full correct-solve history.

    Returns:
        List of dicts with ``challenge_name``, ``category``, ``points``, and
        ``solved_at`` (ISO-8601), ordered newest solve first.
    """
    solves = CTFSubmission.objects.filter(participant_id=participant_id, is_correct=True)
    if freeze_at is not None:
        solves = solves.filter(submitted_at__lt=freeze_at)
    solves = solves.select_related("challenge").order_by("-submitted_at")
    return [
        {
            "challenge_name": solve.challenge.name,
            "category": solve.challenge.category,
            "points": solve.points_awarded,
            "solved_at": solve.submitted_at.isoformat(),
        }
        for solve in solves
    ]


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
    # `is_active_participant`. The shared compete assert also enforces the
    # CTF-604 observer rule at this choke point.
    from ctf.services.participant.queries import assert_participant_can_compete

    assert_participant_can_compete(participant)

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
        safe_log_value(challenge_id),
        safe_log_value(value),
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
