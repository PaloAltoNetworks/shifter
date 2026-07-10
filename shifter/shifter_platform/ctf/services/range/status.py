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
