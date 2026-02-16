"""CTF Range service.

Provides integration with Shifter's range infrastructure for CTF events.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFEvent, CTFParticipant

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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
    logger.info("Provisioning range for participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        )

    # TODO: Implement actual range provisioning via CMS
    # This will call cms.services.create_range() with appropriate RequestSpec

    logger.warning("Range provisioning not yet implemented for participant %s", participant_id)

    return {
        "participant_id": str(participant_id),
        "range_instance_id": None,
        "status": "not_implemented",
    }


def provision_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Provision ranges for all participants in an event.

    Used for scheduled bulk provisioning before event start.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of successful, failed, and pending provisions.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Bulk provisioning ranges for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        )

    participants = CTFParticipant.objects.filter(
        event=event,
        range_instance_id__isnull=True,
    )

    # TODO: Implement bulk provisioning
    # May need to batch/throttle for large events

    logger.warning(
        "Bulk range provisioning not yet implemented for event %s (%d participants)",
        event_id,
        participants.count(),
    )

    return {
        "event_id": str(event_id),
        "total": participants.count(),
        "successful": 0,
        "failed": 0,
        "pending": participants.count(),
    }


def get_range_status(participant_id: UUID) -> dict[str, Any]:
    """Get range status for a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with range status information.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        )

    if not participant.range_instance_id:
        return {
            "participant_id": str(participant_id),
            "status": "not_assigned",
            "range_instance_id": None,
        }

    # TODO: Query actual range status from CMS/Engine
    return {
        "participant_id": str(participant_id),
        "status": participant.range_status or "unknown",
        "range_instance_id": participant.range_instance_id,
    }


def get_range_access_url(
    participant_id: UUID,
    connection_type: str = "rdp",
) -> str | None:
    """Get access URL for participant's range.

    Uses Guacamole integration to generate access URL.

    Args:
        participant_id: UUID of the participant.
        connection_type: Type of connection (rdp, ssh, vnc).

    Returns:
        Access URL or None if not available.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If range is not ready.
    """
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        )

    if not participant.range_instance_id:
        raise CTFRangeError(
            "No range assigned to participant",
            details={"participant_id": str(participant_id)},
        )

    if participant.range_status != "ready":
        raise CTFRangeError(
            f"Range is not ready (status: {participant.range_status})",
            details={
                "participant_id": str(participant_id),
                "status": participant.range_status,
            },
        )

    # TODO: Implement actual Guacamole URL generation
    # This will use mission_control.guacamole.create_rdp_url() or similar

    logger.warning("Range access URL generation not yet implemented")
    return None


def cleanup_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Cleanup (destroy) all ranges for an event.

    Used for scheduled post-event cleanup.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of destroyed and failed cleanups.

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
        )

    participants = CTFParticipant.objects.filter(
        event=event,
        range_instance_id__isnull=False,
    )

    # TODO: Implement range cleanup
    # This will call cms.services.destroy_range() for each range

    logger.warning(
        "Range cleanup not yet implemented for event %s (%d ranges)",
        event_id,
        participants.count(),
    )

    return {
        "event_id": str(event_id),
        "total": participants.count(),
        "destroyed": 0,
        "failed": 0,
    }
