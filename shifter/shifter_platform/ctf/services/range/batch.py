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
    capacity = _declare_and_assess(event_id)
    if capacity is not None and capacity["blocking"]:
        return _capacity_refused_result(event_id, capacity)
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
        return _empty_batch_result(event_id, capacity)

    delay = compute_throttle_delay(spinup_window_seconds, count)

    tallies = {"successful": 0, "failed": 0, "skipped": 0}
    errors: list[dict[str, str]] = []

    interrupted = _provision_participants_paced(
        event_id,
        participants,
        delay,
        tallies,
        errors,
        shutdown_check=shutdown_check,
        heartbeat=heartbeat,
    )

    _notify_provision_failures(event_id, errors)
    if capacity is not None and capacity["outcome"] != "admitted":
        # Advisory/indeterminate outcomes proceeded, but the operator still
        # needs to see them.
        _notify_capacity_outcome(event_id, capacity)

    return {
        "event_id": str(event_id),
        "total": tallies["successful"] + tallies["failed"] + tallies["skipped"],
        "successful": tallies["successful"],
        "failed": tallies["failed"],
        "skipped": tallies["skipped"],
        "errors": errors,
        "interrupted": interrupted,
        "capacity": capacity,
    }


def _provision_participants_paced(
    event_id: UUID,
    participants: list[CTFParticipant],
    delay: float,
    tallies: dict[str, int],
    errors: list[dict[str, str]],
    *,
    shutdown_check: Callable[[], bool] | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> bool:
    """Provision each participant in turn, waiting ``delay`` seconds between them.

    Outcomes are folded into ``tallies`` and ``errors`` in place. Returns whether
    ``shutdown_check`` asked the run to abort before the list was exhausted.
    """
    count = len(participants)
    for i, participant in enumerate(participants):
        if shutdown_check and shutdown_check():
            logger.info(
                "Throttled provisioning interrupted at %d/%d for event %s",
                i,
                count,
                event_id,
            )
            return True

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
    return False


def _declare_and_assess(event_id: UUID) -> dict[str, Any] | None:
    """Declare the wave size, then assess it against observed headroom.

    CTF-908 declares before the first range spins up; PLAT-201 assesses that
    declaration while there is still time to act, so an enforcing over-limit
    metric refuses here rather than letting the event discover the shortfall
    mid-spinup.
    """
    from ctf.services.range.capacity import assess_declared_capacity, declare_event_capacity

    declare_event_capacity(event_id, source="spin_up_ranges")
    return assess_declared_capacity(event_id, source="spin_up_ranges")


def _capacity_refused_result(event_id: UUID, capacity: dict[str, Any]) -> dict[str, Any]:
    """Result shape for a wave refused before any range spun up (PLAT-201).

    Refusing here is the whole point of the requirement: the alternative is
    provisioning most of a cohort and failing partway through, leaving operators
    to clean up half an event. The organizer is notified with bounded reason
    codes only -- never the underlying quota figures.
    """
    logger.warning(
        "Capacity assessment refused spin-up for event %s: %s",
        event_id,
        capacity["reason_codes"],
    )
    _notify_capacity_outcome(event_id, capacity)
    result = _empty_batch_result(event_id, capacity)
    result["refused"] = True
    return result


def _notify_capacity_outcome(event_id: UUID, capacity: dict[str, Any]) -> None:
    """Tell the organizer about a refusal or warning; never raises into spin-up."""
    try:
        from ctf.services.notification import notify_organizer_capacity_outcome

        notify_organizer_capacity_outcome(event_id, capacity)
    except Exception:
        logger.exception("Failed to notify organizer of capacity outcome for event %s", event_id)


def _empty_batch_result(event_id: UUID, capacity: dict[str, Any] | None = None) -> dict[str, Any]:
    """Result shape for an event with nothing left to provision.

    Carries the capacity summary too, so a caller reading the result gets the
    same assessment view whether or not there was anything to provision.
    """
    return {
        "event_id": str(event_id),
        "total": 0,
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "interrupted": False,
        "capacity": capacity,
    }


def _notify_provision_failures(event_id: UUID, errors: list[dict[str, str]]) -> None:
    """Notify the organizer and each affected participant of failures (CTF-801)."""
    if not errors:
        return
    from ctf.services.notification import (
        notify_organizer_provision_failure,
        notify_participant_provision_failure,
    )

    notify_organizer_provision_failure(event_id, errors)
    for error in errors:
        participant_id = error.get("participant_id") if isinstance(error, dict) else None
        if participant_id:
            notify_participant_provision_failure(UUID(str(participant_id)))
