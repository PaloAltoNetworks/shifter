"""Submission pacing gates: attempt limits and cooldowns (python:S104 split).

Extracted from :mod:`ctf.services.submission`; behavior unchanged. These run
under the participant row lock taken by the submission flow, so their reads
are authoritative.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from ctf.exceptions import CTFRateLimitError
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant, CTFSubmission


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
        # window has reset
        return 0

    # the most recent submission
    count = 1
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i] - timestamps[i + 1]).total_seconds()
        if gap >= cooldown_seconds:
            # found a reset boundary
            break
        count += 1

    return count


def _check_attempt_limit_or_raise(
    all_submissions: QuerySet[CTFSubmission],
    event: CTFEvent,
    challenge: CTFChallenge,
    challenge_id: UUID,
) -> int:
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


def _check_submission_cooldown_or_raise(
    participant: CTFParticipant, challenge: CTFChallenge, challenge_id: UUID
) -> None:
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
