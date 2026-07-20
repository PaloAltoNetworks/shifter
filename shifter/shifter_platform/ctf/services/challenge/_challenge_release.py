"""CTF challenge scheduled release: HIDDEN -> VISIBLE at ``release_time``.

``release_challenge`` is invoked by the scheduler (RELEASE_CHALLENGE task);
``_sync_release_task`` is called from the challenge write path
(``_challenge_write``) whenever a challenge is created or updated, to keep
the scheduled task in sync with the current ``visibility`` / ``release_time``.
"""

from __future__ import annotations

import logging
from uuid import UUID

from django.utils import timezone

from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFChallenge

logger = logging.getLogger(__name__)


def release_challenge(challenge_id: UUID) -> CTFChallenge:
    """Transition a challenge from HIDDEN to VISIBLE at its scheduled release time.

    Called by the scheduler when a RELEASE_CHALLENGE task fires.

    Args:
        challenge_id: UUID of the challenge to release.

    Returns:
        The updated CTFChallenge instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
    """
    from ctf.enums import ChallengeVisibility

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    if challenge.visibility != ChallengeVisibility.HIDDEN.value:
        logger.info(
            "Challenge %s is already %s, skipping release",
            challenge_id,
            challenge.visibility,
        )
        return challenge

    challenge.visibility = ChallengeVisibility.VISIBLE.value
    challenge.save(update_fields=["visibility", "updated_at"])
    logger.info("Released challenge %s: HIDDEN -> VISIBLE", challenge_id)
    return challenge


def _sync_release_task(challenge: CTFChallenge) -> None:
    """Create or cancel the RELEASE_CHALLENGE scheduled task for a challenge.

    Cancels any existing pending release task for the challenge, then creates
    a new one if the challenge is HIDDEN with a future release_time.
    """
    from ctf.enums import ChallengeVisibility, ScheduledTaskStatus, ScheduledTaskType
    from ctf.models import CTFScheduledTask

    # Cancel any existing pending release task for this challenge
    pending = CTFScheduledTask.objects.filter(
        event=challenge.event,
        task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
        status=ScheduledTaskStatus.PENDING.value,
        metadata__challenge_id=str(challenge.pk),
    )
    for task in pending:
        task.mark_cancelled()

    # Schedule a new release task if challenge is HIDDEN with a future release_time
    if (
        challenge.release_time is not None
        and challenge.visibility == ChallengeVisibility.HIDDEN.value
        and challenge.release_time > timezone.now()
    ):
        CTFScheduledTask.objects.create(
            event=challenge.event,
            task_type=ScheduledTaskType.RELEASE_CHALLENGE.value,
            scheduled_for=challenge.release_time,
            metadata={"challenge_id": str(challenge.pk)},
        )
        logger.info(
            "Scheduled release for challenge %s at %s",
            challenge.pk,
            challenge.release_time,
        )
