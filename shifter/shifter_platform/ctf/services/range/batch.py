"""Event-level throttled range provisioning.

Spreads per-participant provisioning across a spin-up window so a large event
does not overwhelm AWS with simultaneous ECS tasks, keeping the scheduler task
and liveness file fresh throughout. Builds on the single-participant retry and
keep-alive primitives in :mod:`ctf.services.range.provision`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.range.provision import (
    _interruptible_sleep,
    _is_already_assigned_error,
    provision_participant_range_with_retry,
)

logger = logging.getLogger(__name__)

# Per-participant delay is clamped to this inclusive band (seconds) so a tiny
# window cannot hammer AWS and an enormous window cannot stall the spin-up.
_MIN_THROTTLE_DELAY_SECONDS = 5.0
_MAX_THROTTLE_DELAY_SECONDS = 120.0


def compute_throttle_delay(spinup_window_seconds: int, participant_count: int) -> float:
    """Per-participant delay (seconds) to spread a spin-up across the window.

    Pure function: ``spinup_window_seconds`` divided across the participants and
    clamped to ``[5, 120]`` seconds. Extracted as a seam so scheduler/capacity
    work (#942/#943) and app-saturation signals (#940) can shape pacing without
    re-editing the throttled loop.
    """
    raw_delay = spinup_window_seconds / max(participant_count, 1)
    return max(_MIN_THROTTLE_DELAY_SECONDS, min(_MAX_THROTTLE_DELAY_SECONDS, raw_delay))


def _safe_heartbeat(heartbeat: Callable[[], None] | None, event_id: UUID) -> None:
    """Invoke the spin-up heartbeat, swallowing failures (#942).

    Keeps the claimed scheduled task fresh so the stale-recovery sweep does not
    mark this in-flight spin-up FAILED. A heartbeat error must never abort the
    spin-up.
    """
    if heartbeat is None:
        return
    try:
        heartbeat()
    except Exception:
        # A persistently failing heartbeat is what re-opens the stale-sweep bug
        # this guards against, so surface it (with traceback) rather than hide it.
        logger.exception("Spin-up heartbeat failed for event %s", event_id)


def _record_provision_attempt(
    participant: CTFParticipant,
    tallies: dict[str, int],
    errors: list[dict[str, str]],
    heartbeat: Callable[[], None] | None = None,
) -> None:
    """Provision one participant and fold the outcome into the running tallies.

    A benign 'already has a range' race loser is counted as ``skipped`` rather
    than ``failed`` so it does not poison the event spin-up (#942). The
    ``heartbeat`` is forwarded so the per-participant retry backoff also keeps
    the scheduled task and liveness file fresh (#943).
    """
    try:
        provision_participant_range_with_retry(participant.pk, heartbeat=heartbeat)
        tallies["successful"] += 1
    except Exception as e:
        if _is_already_assigned_error(e):
            tallies["skipped"] += 1
            logger.info("Participant %s already has a range; skipping", participant.pk)
        else:
            tallies["failed"] += 1
            errors.append({"participant_id": str(participant.pk), "error": str(e)})
            logger.exception("Failed to provision range for participant %s", participant.pk)


def provision_event_ranges_throttled(
    event_id: UUID,
    spinup_window_seconds: int,
    shutdown_check: Callable[[], bool] | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Provision ranges for all participants with throttled pacing.

    Spreads provisioning requests across ``spinup_window_seconds`` to avoid
    overwhelming AWS with simultaneous ECS tasks.

    Args:
        event_id: UUID of the event.
        spinup_window_seconds: Total window (seconds) over which to spread requests.
        shutdown_check: Optional callable returning True when the caller
            wants to abort (e.g. SIGTERM received by management command).
        heartbeat: Optional callable invoked between provisions and during the
            inter-provision waits so a long run keeps both its scheduled task
            fresh (so the stale-recovery sweep does not mark it FAILED on the
            multi-node portal, #942) and the scheduler liveness file fresh (so
            the container healthcheck does not restart it, #943). Failures are
            swallowed so a heartbeat error never aborts provisioning.

    Returns:
        Dict with counts of successful, failed, skipped, and whether interrupted.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info(
        "Throttled provisioning for event %s (window=%ds)",
        event_id,
        spinup_window_seconds,
    )

    try:
        CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = list(
        CTFParticipant.objects.filter(
            event_id=event_id,
            range_instance_id__isnull=True,
        )
    )

    count = len(participants)
    if count == 0:
        return {
            "event_id": str(event_id),
            "total": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "interrupted": False,
        }

    delay = compute_throttle_delay(spinup_window_seconds, count)

    tallies = {"successful": 0, "failed": 0, "skipped": 0}
    errors: list[dict[str, str]] = []
    interrupted = False

    for i, participant in enumerate(participants):
        if shutdown_check and shutdown_check():
            logger.info(
                "Throttled provisioning interrupted at %d/%d for event %s",
                i,
                count,
                event_id,
            )
            interrupted = True
            break

        _safe_heartbeat(heartbeat, event_id)
        _record_provision_attempt(participant, tallies, errors, heartbeat=heartbeat)

        logger.info(
            "Throttled provisioning progress for event %s: %d/%d (%d ready, %d failed, %d skipped)",
            event_id,
            i + 1,
            count,
            tallies["successful"],
            tallies["failed"],
            tallies["skipped"],
        )

        # Sleep between provisions (skip after the last one). The wait is
        # chunked so the heartbeat stays fresh and shutdown stays responsive.
        if i < count - 1 and not (shutdown_check and shutdown_check()):
            _interruptible_sleep(delay, heartbeat=heartbeat, shutdown_check=shutdown_check)

    # Notify organizer of failures
    if errors:
        from ctf.services.notification import notify_organizer_provision_failure

        notify_organizer_provision_failure(event_id, errors)

    return {
        "event_id": str(event_id),
        "total": tallies["successful"] + tallies["failed"] + tallies["skipped"],
        "successful": tallies["successful"],
        "failed": tallies["failed"],
        "skipped": tallies["skipped"],
        "errors": errors,
        "interrupted": interrupted,
    }
