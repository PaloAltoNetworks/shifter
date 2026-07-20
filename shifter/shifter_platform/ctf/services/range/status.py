"""Participant range status reads.

Reads a participant's range status (refreshing the cached value from CMS) and
provides the participant-with-range loader shared by the lifecycle actions in
:mod:`ctf.services.range.lifecycle`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFParticipant


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
            "vpn_profile_available": False,
        }

    # Query CMS for fresh status via bridge
    from ctf.bridges import cms_get_range_status

    fresh_status = cms_get_range_status(participant.range_instance_id)

    # Update cached status if changed
    if fresh_status != participant.range_status:
        became_ready = fresh_status == "ready" and participant.range_status != "ready"
        participant.range_status = fresh_status
        participant.save(update_fields=["range_status", "updated_at"])
        if became_ready:
            _notify_range_ready(participant)

    vpn_profile_available = False
    # Expose the participant-safe target boxes only once the range is ready so the
    # SPA workspace can render per-box access (#1740). The bridge projects to the
    # {uuid, name, private_ip, os_type} allowlist; outside the ready state we
    # return an empty list rather than leaking stale targets.
    target_instances: list[dict[str, str]] = []
    if participant.user_id:
        from ctf.bridges import cms_get_range_target_instances, cms_has_openvpn_profile

        user = participant.user
        if user is not None:
            vpn_profile_available = cms_has_openvpn_profile(user, participant.range_instance_id)
            if participant.range_status == "ready":
                target_instances = cms_get_range_target_instances(user)

    return {
        "participant_id": str(participant_id),
        "status": participant.range_status,
        "range_instance_id": participant.range_instance_id,
        "vpn_profile_available": vpn_profile_available,
        "target_instances": target_instances,
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


def _get_participant_with_range(participant_id: UUID) -> CTFParticipant:
    """Load participant, validate it has a range and a linked user."""
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

    if participant.user is None:
        raise CTFRangeError(
            "Participant has no linked user",
            details={"participant_id": str(participant_id)},
        )

    return participant


def _notify_range_ready(participant: CTFParticipant) -> None:
    """Range-ready milestone (CTF-801/CTF-802): email + realtime, best-effort."""
    try:
        from ctf.services.notification import publish_event_notification, send_range_ready

        send_range_ready(participant.pk)
        if participant.user_id:
            publish_event_notification(
                participant.event,
                "range_ready",
                {"participant_id": str(participant.pk)},
                recipient_ids=[participant.user_id],
            )
    # pragma: no cover — defensive; notification must never break status reads
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Range-ready notification failed for %s", participant.pk)
