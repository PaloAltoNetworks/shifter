"""CTF Bracket service.

Provides business logic for bracket CRUD and participant assignment.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from ctf.models import CTFBracket, CTFParticipant
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def create_bracket(
    event_id: UUID,
    name: str,
    description: str = "",
    display_order: int = 0,
) -> CTFBracket:
    """Create a bracket for an event.

    Args:
        event_id: UUID of the event.
        name: Bracket display name.
        description: Optional bracket description.
        display_order: Sort order for display.

    Returns:
        The created CTFBracket instance.
    """
    bracket = CTFBracket(
        event_id=event_id,
        name=name,
        description=description,
        display_order=display_order,
    )
    bracket.save()
    logger.info("Created bracket '%s' for event %s", name, event_id)
    return bracket


def update_bracket(bracket_id: UUID, **kwargs: Any) -> CTFBracket:
    """Update a bracket.

    Args:
        bracket_id: UUID of the bracket.
        **kwargs: Fields to update (name, description, display_order).

    Returns:
        The updated CTFBracket instance.

    Raises:
        CTFBracket.DoesNotExist: If bracket not found.
    """
    bracket = CTFBracket.objects.get(pk=bracket_id)
    allowed_fields = {"name", "description", "display_order"}
    update_fields = []
    for field, value in kwargs.items():
        if field in allowed_fields:
            setattr(bracket, field, value)
            update_fields.append(field)
    if update_fields:
        update_fields.append("updated_at")
        bracket.save(update_fields=update_fields)
        logger.info("Updated bracket %s: %s", bracket_id, update_fields)
    return bracket


def delete_bracket(bracket_id: UUID) -> None:
    """Soft-delete a bracket.

    Unassigns all participants from the bracket before deleting.

    Args:
        bracket_id: UUID of the bracket.

    Raises:
        CTFBracket.DoesNotExist: If bracket not found.
    """
    bracket = CTFBracket.objects.get(pk=bracket_id)
    # Unassign participants from this bracket
    CTFParticipant.objects.filter(bracket=bracket).update(bracket=None)
    bracket.delete()
    logger.info("Deleted bracket %s", bracket_id)


def list_brackets(event_id: UUID) -> QuerySet[CTFBracket]:
    """List all brackets for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFBracket ordered by display_order, name.
    """
    return CTFBracket.objects.filter(event_id=event_id)


def get_bracket(bracket_id: UUID) -> CTFBracket:
    """Get a bracket by ID.

    Args:
        bracket_id: UUID of the bracket.

    Returns:
        The CTFBracket instance.

    Raises:
        CTFBracket.DoesNotExist: If bracket not found.
    """
    return CTFBracket.objects.get(pk=bracket_id)


def assign_participant_bracket(participant_id: UUID, bracket_id: UUID) -> CTFParticipant:
    """Assign a participant to a bracket.

    Validates that the bracket belongs to the same event as the participant.

    Args:
        participant_id: UUID of the participant.
        bracket_id: UUID of the bracket.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFParticipant.DoesNotExist: If participant not found.
        CTFBracket.DoesNotExist: If bracket not found.
        ValidationError: If bracket and participant belong to different events.
    """
    participant = CTFParticipant.objects.get(pk=participant_id)
    bracket = CTFBracket.objects.get(pk=bracket_id)

    if participant.event_id != bracket.event_id:
        raise ValidationError("Bracket and participant must belong to the same event.")

    participant.bracket = bracket
    participant.save(update_fields=["bracket", "updated_at"])
    logger.info("Assigned participant %s to bracket '%s'", participant_id, safe_log_value(bracket.name))
    return participant


def remove_participant_bracket(participant_id: UUID) -> CTFParticipant:
    """Remove a participant's bracket assignment.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFParticipant.DoesNotExist: If participant not found.
    """
    participant = CTFParticipant.objects.get(pk=participant_id)
    participant.bracket = None
    participant.save(update_fields=["bracket", "updated_at"])
    logger.info("Removed bracket assignment for participant %s", participant_id)
    return participant
