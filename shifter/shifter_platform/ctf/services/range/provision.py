"""Single-participant range provisioning.

Provisions a CTF range for one participant under the assignment lock, with an
exponential-backoff retry wrapper. The keep-alive sleep primitive and the
benign race-loser discriminator live here because both the single-participant
retry and the event-level throttled loop (:mod:`ctf.services.range.batch`)
depend on them.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import transaction

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFParticipant
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

# Throttled provisioning can sleep for up to 120s between participants and the
# retry backoff can wait even longer. The scheduler's liveness heartbeat file
# is checked at a 1-2 minute staleness threshold, so long waits are broken into
# small chunks that touch the heartbeat between them (and stay responsive to
# shutdown) rather than blocking in a single ``time.sleep`` call.
_HEARTBEAT_CHUNK_SECONDS = 15.0


def _interruptible_sleep(
    seconds: float,
    *,
    heartbeat: Callable[[], None] | None = None,
    shutdown_check: Callable[[], bool] | None = None,
) -> None:
    """Sleep ``seconds`` in <=``_HEARTBEAT_CHUNK_SECONDS`` increments.

    Touches ``heartbeat`` before each increment so a long wait does not let the
    scheduler liveness file go stale, and aborts early when ``shutdown_check``
    returns True so the caller stays responsive to SIGTERM.
    """
    remaining = float(seconds)
    while remaining > 0:
        if shutdown_check is not None and shutdown_check():
            return
        if heartbeat is not None:
            # A heartbeat failure during a wait must never abort provisioning;
            # the per-participant call site logs persistent failures (#942).
            with contextlib.suppress(Exception):
                heartbeat()
        chunk = min(_HEARTBEAT_CHUNK_SECONDS, remaining)
        time.sleep(chunk)
        remaining -= chunk


def _is_already_assigned_error(exc: Exception) -> bool:
    """Return True for the benign 'already has a range' race-loser error (#942).

    A second (manual or scheduled) caller that finds a participant already
    assigned should be skipped, not counted as a provisioning failure.
    """
    return isinstance(exc, CTFRangeError) and "already has a range" in str(exc)


def provision_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Provision a range for a participant.

    Uses the event's scenario_id to create a range via CMS.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with range instance ID and initial status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If range provisioning fails.
    """
    logger.info("Provisioning range for participant %s", safe_log_value(participant_id))

    # Lock the participant row for the whole assignment (#942 CTF-7): the
    # already-assigned check, CMS create call, instance-id lookup, and write must
    # be atomic so concurrent manual + scheduled provisioning cannot double-assign
    # a range. No select_related: `user` is nullable (FOR UPDATE rejects the
    # nullable side of an outer join on PostgreSQL) and joining `event` would
    # widen the lock to an event-wide row lock; both load lazily under the lock.
    with transaction.atomic():
        try:
            participant = CTFParticipant.objects.select_for_update().get(pk=participant_id)
        except CTFParticipant.DoesNotExist:
            raise CTFNotFoundError(
                f"Participant {participant_id} not found",
                details={"participant_id": str(participant_id)},
            ) from None

        if participant.user is None:
            raise CTFRangeError(
                "Participant must be registered before provisioning a range",
                details={"participant_id": str(participant_id)},
            )

        # An assignment is "claimed" the moment provisioning starts, not only
        # once a range_instance_id resolves (#942). cms_create_range can succeed
        # while cms_find_range_instance_id still returns None (the RangeInstance
        # row is not yet resolvable from the request id), in which case this
        # function persists range_status="provisioning" with a null
        # range_instance_id. Keying the guard solely on range_instance_id would
        # let the next caller re-provision that participant once the lock
        # releases, creating a second CMS range. Treat an in-progress
        # provisioning state as already-claimed so the benign race-loser path
        # skips it instead.
        if participant.range_instance_id or participant.range_status == "provisioning":
            raise CTFRangeError(
                "Participant already has a range assigned",
                details={
                    "participant_id": str(participant_id),
                    "range_instance_id": participant.range_instance_id,
                    "range_status": participant.range_status,
                },
            )

        event = participant.event
        agents_by_os = event.range_config.get("agents_by_os", {}) if event.range_config else {}
        ngfw_enabled = event.range_config.get("ngfw_enabled", False) if event.range_config else False

        try:
            from ctf.bridges import cms_create_range, cms_find_range_instance_id

            result = cms_create_range(
                user=participant.user,
                scenario=event.scenario_id,
                agents_by_os=agents_by_os,
                ngfw_enabled=ngfw_enabled,
            )
        except Exception as e:
            logger.exception("Range provisioning failed for participant %s", safe_log_value(participant_id))
            raise CTFRangeError(
                f"Range provisioning failed: {e}",
                details={"participant_id": str(participant_id)},
            ) from e

        # Store the RangeInstance reference
        range_instance_id = cms_find_range_instance_id(result.request_id)

        if range_instance_id:
            participant.range_instance_id = range_instance_id
        participant.range_status = "provisioning"
        participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])

    return {
        "participant_id": str(participant_id),
        "range_instance_id": participant.range_instance_id,
        "status": "provisioning",
    }


def provision_participant_range_with_retry(
    participant_id: UUID,
    max_retries: int = 3,
    base_delay: int = 30,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Provision a range with exponential backoff retry.

    Args:
        participant_id: UUID of the participant.
        max_retries: Maximum retry attempts after initial failure.
        base_delay: Base delay in seconds between retries (doubled each attempt).
        heartbeat: Optional callable invoked during backoff waits so the
            scheduler liveness file stays fresh through long retries.

    Returns:
        Dict with range instance ID, status, and retry count.
    """
    last_error = None

    for attempt in range(1 + max_retries):
        try:
            result = provision_participant_range(participant_id)
            if attempt > 0:
                logger.info(
                    "Provisioning succeeded on attempt %d for participant %s",
                    attempt + 1,
                    participant_id,
                )
            result["retries"] = attempt
            return result
        except CTFRangeError as e:
            # Don't retry validation errors (no user, already assigned)
            if "must be registered" in str(e) or "already has a range" in str(e):
                raise
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Provisioning attempt %d failed for participant %s, retrying in %ds: %s",
                    attempt + 1,
                    participant_id,
                    delay,
                    e,
                )
                _interruptible_sleep(delay, heartbeat=heartbeat)

    # All retries exhausted — mark as error
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
        participant.range_status = "error"
        participant.save(update_fields=["range_status", "updated_at"])
    except CTFParticipant.DoesNotExist:
        pass

    logger.error(
        "Provisioning failed after %d attempts for participant %s: %s",
        1 + max_retries,
        participant_id,
        last_error,
    )
    raise CTFRangeError(
        f"Provisioning failed after {1 + max_retries} attempts: {last_error}",
        details={"participant_id": str(participant_id), "retries": max_retries},
    ) from last_error
