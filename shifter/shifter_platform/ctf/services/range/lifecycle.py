"""Participant range lifecycle actions.

Stop / start / restart / destroy a participant's range, and bulk-cleanup all
ranges for an event. Loads participants through the shared validator in
:mod:`ctf.services.range.status`.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.range.status import _get_participant_with_range
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def stop_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Stop (pause) a participant's range."""
    logger.info("Stopping range for participant %s", safe_log_value(participant_id))
    participant = _get_participant_with_range(participant_id)

    from ctf.bridges import cms_stop_range

    # guaranteed by _get_participant_with_range
    assert participant.range_instance_id is not None
    cms_stop_range(participant.user, participant.range_instance_id)
    participant.range_status = "stopping"
    participant.save(update_fields=["range_status", "updated_at"])
    return {"participant_id": str(participant_id), "status": "stopping"}


def start_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Start (resume) a participant's stopped range."""
    logger.info("Starting range for participant %s", safe_log_value(participant_id))
    participant = _get_participant_with_range(participant_id)

    from ctf.bridges import cms_start_range

    # guaranteed by _get_participant_with_range
    assert participant.range_instance_id is not None
    cms_start_range(participant.user, participant.range_instance_id)
    participant.range_status = "resuming"
    participant.save(update_fields=["range_status", "updated_at"])
    return {"participant_id": str(participant_id), "status": "resuming"}


def restart_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Restart a participant's range (stop then start)."""
    logger.info("Restarting range for participant %s", safe_log_value(participant_id))
    stop_participant_range(participant_id)
    return start_participant_range(participant_id)


def destroy_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Destroy range for a single participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with destruction status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If no range assigned.
    """
    logger.info("Destroying range for participant %s", safe_log_value(participant_id))

    try:
        participant = CTFParticipant.objects.select_related("user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if not participant.range_instance_id:
        raise CTFRangeError(
            "No range assigned to participant",
            details={"participant_id": str(participant_id)},
        )

    _destroy_single_range(participant, participant.user)

    # Truthful outcome (ADR-063-R4): the destroy is dispatched, not verified gone.
    # The terminal DESTROYED projection is what confirms teardown.
    return {
        "participant_id": str(participant_id),
        "status": "destroying",
    }


def cleanup_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Cleanup (destroy) all ranges for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of teardowns dispatched (not verified destroyed) and failed.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Cleaning up ranges for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = list(
        CTFParticipant.objects.filter(
            event=event,
            range_instance_id__isnull=False,
        ).select_related("user")
    )

    dispatched = 0
    failed = 0

    # CTF-1003: destroy in batches with a pause between them so a large event
    # does not hammer the cloud APIs into throttling.
    batch_size = max(1, int(getattr(settings, "CTF_RANGE_CLEANUP_BATCH_SIZE", 10)))
    batch_pause = float(getattr(settings, "CTF_RANGE_CLEANUP_BATCH_PAUSE_SECONDS", 5))
    for start in range(0, len(participants), batch_size):
        if start and batch_pause > 0:
            time.sleep(batch_pause)
        for participant in participants[start : start + batch_size]:
            try:
                if _destroy_single_range(participant, participant.user):
                    dispatched += 1
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to dispatch range destroy for participant %s",
                    participant.pk,
                )

    _cleanup_event_spares_best_effort(event_id)

    # Counts are teardowns *dispatched*, not verified destroyed: terminal cleanup
    # is confirmed later by scoped provider inventory/readback (ADR-063-R4).
    return {
        "event_id": str(event_id),
        "total": dispatched + failed,
        "dispatched": dispatched,
        "failed": failed,
    }


def _cleanup_event_spares_best_effort(event_id: UUID) -> None:
    """Tear down the event's spare pool alongside participant-range cleanup (#1018).

    Best-effort: a spare-cleanup failure must never abort the participant-range
    cleanup this runs after, so it is logged and swallowed here.
    """
    from ctf.services.range.spares import cleanup_event_spares

    try:
        cleanup_event_spares(event_id)
    except Exception:
        logger.exception(
            "cleanup_event_ranges: spare-pool cleanup failed for event %s",
            safe_log_value(event_id),
        )


def _destroy_single_range(participant: CTFParticipant, user: User | None) -> bool:
    """Dispatch a participant range destroy without pre-empting terminal cleanup (#1919).

    ``cms_destroy_range`` only *dispatches* the asynchronous destroy; the range is
    not gone when it returns. Capacity release and linkage clearing are deferred to
    the verified terminal cleanup projection (``ctf.signals.
    sync_ctf_participant_range_status`` gated on scoped provider inventory/readback
    evidence) so the participant/range/reservation linkage is retained until the
    resources are actually gone -- a reusable slot is never returned, and cleanup
    success is never reported, while unresolved resources can still own it
    (ADR-063-R4/R5). The reconciler remains the backstop for a range whose terminal
    projection never arrives.

    Returns the dispatch disposition: ``True`` when a destroy was dispatched,
    ``False`` when skipped (no range or no owner). It is a dispatch signal, never a
    "destroyed" or verified-cleanup signal -- callers must not report completion
    from it.
    """
    from ctf.bridges import cms_destroy_range

    if participant.range_instance_id is None:
        logger.warning("No range_instance_id for participant %s, skipping destroy", participant.pk)
        return False
    if user is None:
        logger.warning("No user for participant %s, skipping destroy", participant.pk)
        return False
    cms_destroy_range(user, participant.range_instance_id)
    participant.range_status = "destroying"
    participant.save(update_fields=["range_status", "updated_at"])
    return True
