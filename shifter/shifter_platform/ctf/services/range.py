"""CTF Range service.

Provides integration with Shifter's range infrastructure for CTF events.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
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
        participant = CTFParticipant.objects.select_related("event", "user").get(pk=participant_id)
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

    if participant.range_instance_id:
        raise CTFRangeError(
            "Participant already has a range assigned",
            details={
                "participant_id": str(participant_id),
                "range_instance_id": participant.range_instance_id,
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
        logger.exception("Range provisioning failed for participant %s", participant_id)
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


def provision_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Provision ranges for all participants in an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of successful, failed, and pending provisions.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Bulk provisioning ranges for event %s", event_id)

    try:
        CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event_id=event_id,
        range_instance_id__isnull=True,
    )

    successful = 0
    failed = 0
    errors = []

    for participant in participants:
        try:
            provision_participant_range(participant.pk)
            successful += 1
        except Exception as e:
            failed += 1
            errors.append({"participant_id": str(participant.pk), "error": str(e)})
            logger.error(
                "Failed to provision range for participant %s: %s",
                participant.pk,
                e,
            )

    return {
        "event_id": str(event_id),
        "total": successful + failed,
        "successful": successful,
        "failed": failed,
        "errors": errors,
    }


def provision_event_ranges_throttled(
    event_id: UUID,
    spinup_window_seconds: int,
    shutdown_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Provision ranges for all participants with throttled pacing.

    Spreads provisioning requests across ``spinup_window_seconds`` to avoid
    overwhelming AWS with simultaneous ECS tasks.

    Args:
        event_id: UUID of the event.
        spinup_window_seconds: Total window (seconds) over which to spread requests.
        shutdown_check: Optional callable returning True when the caller
            wants to abort (e.g. SIGTERM received by management command).

    Returns:
        Dict with counts of successful, failed, and whether interrupted.

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
            "errors": [],
            "interrupted": False,
        }

    # Delay between provisions, clamped to [5, 120] seconds
    raw_delay = spinup_window_seconds / max(count, 1)
    delay = max(5.0, min(120.0, raw_delay))

    successful = 0
    failed = 0
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

        try:
            provision_participant_range(participant.pk)
            successful += 1
        except Exception as e:
            failed += 1
            errors.append({"participant_id": str(participant.pk), "error": str(e)})
            logger.error(
                "Failed to provision range for participant %s: %s",
                participant.pk,
                e,
            )

        # Sleep between provisions (skip after the last one)
        if i < count - 1 and not (shutdown_check and shutdown_check()):
            time.sleep(delay)

    return {
        "event_id": str(event_id),
        "total": successful + failed,
        "successful": successful,
        "failed": failed,
        "errors": errors,
        "interrupted": interrupted,
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
        ) from None

    if not participant.range_instance_id:
        return {
            "participant_id": str(participant_id),
            "status": "not_assigned",
            "range_instance_id": None,
        }

    # Query CMS for fresh status via bridge
    from ctf.bridges import cms_get_range_status

    fresh_status = cms_get_range_status(participant.range_instance_id)

    # Update cached status if changed
    if fresh_status != participant.range_status:
        participant.range_status = fresh_status
        participant.save(update_fields=["range_status", "updated_at"])

    return {
        "participant_id": str(participant_id),
        "status": participant.range_status,
        "range_instance_id": participant.range_instance_id,
    }


def get_range_access_url(
    participant_id: UUID,
    connection_type: str = "rdp",
) -> str | None:
    """Get access URL for participant's range.

    Args:
        participant_id: UUID of the participant.
        connection_type: Type of connection (rdp, ssh, vnc).

    Returns:
        Access URL string.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If range is not ready.
    """
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

    if participant.range_status != "ready":
        raise CTFRangeError(
            f"Range is not ready (status: {participant.range_status})",
            details={
                "participant_id": str(participant_id),
                "status": participant.range_status,
            },
        )

    from ctf.bridges import get_guacamole_rdp_url, get_range_connection_info

    if participant.user is None:
        raise CTFRangeError(
            "Participant has no linked user",
            details={"participant_id": str(participant_id)},
        )

    username = participant.user.email

    try:
        conn = get_range_connection_info(
            user=participant.user,
            range_instance_id=participant.range_instance_id,
        )
    except ValueError as e:
        raise CTFRangeError(
            f"Cannot resolve range connection info: {e}",
            details={"range_instance_id": participant.range_instance_id},
        ) from e

    url = get_guacamole_rdp_url(
        username=username,
        connection_name=conn["connection_name"],
        hostname=conn["private_ip"],
        rdp_username=conn.get("rdp_username"),
        rdp_password=conn.get("rdp_password"),
        sftp_root_directory=conn.get("sftp_root_directory"),
        sftp_private_key=conn.get("ssh_key"),
    )

    return url


def cleanup_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Cleanup (destroy) all ranges for an event.

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
        ) from None

    participants = CTFParticipant.objects.filter(
        event=event,
        range_instance_id__isnull=False,
    ).select_related("user")

    destroyed = 0
    failed = 0

    for participant in participants:
        try:
            _destroy_single_range(participant, participant.user)
            destroyed += 1
        except Exception as e:
            failed += 1
            logger.error(
                "Failed to destroy range for participant %s: %s",
                participant.pk,
                e,
            )

    return {
        "event_id": str(event_id),
        "total": destroyed + failed,
        "destroyed": destroyed,
        "failed": failed,
    }


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
    logger.info("Destroying range for participant %s", participant_id)

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

    return {
        "participant_id": str(participant_id),
        "status": "destroyed",
    }


def update_participant_range_status(participant_id: UUID) -> dict[str, Any]:
    """Poll CMS for fresh range status and update cached value.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with updated status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    return get_range_status(participant_id)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _destroy_single_range(participant: CTFParticipant, user) -> None:
    """Destroy a single participant's range and clear fields."""
    from ctf.bridges import cms_destroy_range

    if participant.range_instance_id is None:
        logger.warning("No range_instance_id for participant %s, skipping destroy", participant.pk)
        return
    if user is None:
        logger.warning("No user for participant %s, skipping destroy", participant.pk)
        return
    cms_destroy_range(user, participant.range_instance_id)
    participant.range_instance_id = None
    participant.range_status = ""
    participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
