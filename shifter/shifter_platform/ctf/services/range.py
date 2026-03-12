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
        import cms.services as cms_services

        result = cms_services.create_range(
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
    # RangeContext has request_id (UUID) - we need to find the RangeInstance by request
    from cms.models import RangeInstance

    range_instance = RangeInstance.objects.filter(request__request_id=result.request_id).first()

    if range_instance:
        participant.range_instance_id = range_instance.pk
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

    # Query CMS for fresh status
    from cms.models import RangeInstance

    try:
        range_instance = RangeInstance.objects.get(pk=participant.range_instance_id)
        fresh_status = range_instance.status
    except RangeInstance.DoesNotExist:
        fresh_status = "unknown"

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

    # Load RangeInstance for IP extraction
    from cms.models import RangeInstance

    try:
        range_instance = RangeInstance.objects.get(pk=participant.range_instance_id)
    except RangeInstance.DoesNotExist:
        raise CTFRangeError(
            "Range instance not found in CMS",
            details={"range_instance_id": participant.range_instance_id},
        ) from None

    # Extract IP from range_spec
    private_ip = _extract_ip_from_range_spec(range_instance.range_spec)
    if not private_ip:
        raise CTFRangeError(
            "No IP address found in range spec",
            details={"range_instance_id": participant.range_instance_id},
        )

    # Generate Guacamole URL
    from django.conf import settings

    from mission_control.guacamole import create_guacamole_rdp_url

    username = participant.user.email if participant.user else participant.email

    url = create_guacamole_rdp_url(
        base_url=settings.GUACAMOLE_BASE_URL,
        secret_key=settings.GUACAMOLE_JSON_AUTH_SECRET,
        username=username,
        connection_name=f"ctf-{participant.id}",
        hostname=private_ip,
        api_base_url=settings.GUACAMOLE_API_BASE_URL,
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
    import cms.services as cms_services

    if participant.range_instance_id is None:
        logger.warning("No range_instance_id for participant %s, skipping destroy", participant.pk)
        return
    if user is None:
        logger.warning("No user for participant %s, skipping destroy", participant.pk)
        return
    cms_services.destroy_range(user, participant.range_instance_id)
    participant.range_instance_id = None
    participant.range_status = ""
    participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])


def _extract_ip_from_range_spec(range_spec: dict | None) -> str | None:
    """Extract first private IP from range_spec.

    Supports both new format (subnets[*].instances) and legacy (instances[*]).
    """
    if not range_spec:
        return None

    # New format: subnets -> instances
    subnets = range_spec.get("subnets", [])
    for subnet in subnets:
        instances = subnet.get("instances", [])
        for instance in instances:
            ip = instance.get("private_ip")
            if ip:
                return ip

    # Legacy format: instances directly
    instances = range_spec.get("instances", [])
    for instance in instances:
        ip = instance.get("private_ip")
        if ip:
            return ip

    return None
