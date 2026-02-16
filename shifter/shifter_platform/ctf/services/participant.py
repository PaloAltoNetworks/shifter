"""CTF Participant service.

Provides business logic for participant management.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant, CTFTeam

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def invite_participant(
    event_id: UUID,
    email: str,
    name: str,
    team_id: UUID | None = None,
) -> CTFParticipant:
    """Invite a participant to a CTF event.

    Args:
        event_id: UUID of the event.
        email: Participant's email address.
        name: Participant's display name.
        team_id: Optional team UUID to assign.

    Returns:
        The created CTFParticipant instance.

    Raises:
        CTFNotFoundError: If event or team doesn't exist.
        CTFValidationError: If participant already exists or data is invalid.
    """
    logger.info("Inviting participant %s to event %s", email, event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        )

    # Check max participants
    if event.max_participants:
        current_count = event.participants.count()
        if current_count >= event.max_participants:
            raise CTFValidationError(
                f"Event has reached maximum participants ({event.max_participants})",
                code="CTF_MAX_PARTICIPANTS_REACHED",
                details={"event_id": str(event_id), "max": event.max_participants},
            )

    # Check for existing participant
    if CTFParticipant.objects.filter(event=event, email__iexact=email).exists():
        raise CTFValidationError(
            f"Participant with email {email} already exists in this event",
            code="CTF_DUPLICATE_PARTICIPANT",
            details={"email": email, "event_id": str(event_id)},
        )

    team = None
    if team_id:
        try:
            team = CTFTeam.objects.get(pk=team_id, event=event)
        except CTFTeam.DoesNotExist:
            raise CTFNotFoundError(
                f"Team {team_id} not found in event {event_id}",
                details={"team_id": str(team_id), "event_id": str(event_id)},
            )

    with transaction.atomic():
        participant = CTFParticipant.objects.create(
            event=event,
            email=email.lower().strip(),
            name=name.strip(),
            team=team,
            status=ParticipantStatus.INVITED.value,
            invited_at=timezone.now(),
        )

        logger.info(
            "Invited participant %s to event %s (id: %s)",
            email,
            event_id,
            participant.id,
        )

    return participant


def bulk_import_participants(
    event_id: UUID,
    csv_content: str,
) -> list[CTFParticipant]:
    """Bulk import participants from CSV content.

    CSV format: name,email (one per line)

    Args:
        event_id: UUID of the event.
        csv_content: CSV string with participant data.

    Returns:
        List of created CTFParticipant instances.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFValidationError: If CSV format is invalid.
    """
    logger.info("Bulk importing participants to event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        )

    # Parse CSV
    reader = csv.reader(io.StringIO(csv_content))
    participants_data: list[tuple[str, str]] = []
    errors: list[str] = []

    for line_num, row in enumerate(reader, start=1):
        if not row or (len(row) == 1 and not row[0].strip()):
            continue  # Skip empty lines

        if len(row) < 2:
            errors.append(f"Line {line_num}: Expected name,email format")
            continue

        name = row[0].strip()
        email = row[1].strip().lower()

        if not name:
            errors.append(f"Line {line_num}: Name is required")
            continue

        if not email or "@" not in email:
            errors.append(f"Line {line_num}: Invalid email format")
            continue

        participants_data.append((name, email))

    if errors:
        raise CTFValidationError(
            "CSV validation errors",
            code="CTF_CSV_VALIDATION_ERROR",
            details={"errors": errors},
        )

    # Check for duplicates within the import
    seen_emails: set[str] = set()
    duplicates: list[str] = []
    for name, email in participants_data:
        if email in seen_emails:
            duplicates.append(email)
        seen_emails.add(email)

    if duplicates:
        raise CTFValidationError(
            "Duplicate emails in import",
            code="CTF_DUPLICATE_EMAILS",
            details={"duplicates": duplicates},
        )

    # Check for existing participants
    existing = CTFParticipant.objects.filter(
        event=event,
        email__in=seen_emails,
    ).values_list("email", flat=True)

    if existing:
        raise CTFValidationError(
            "Some participants already exist",
            code="CTF_EXISTING_PARTICIPANTS",
            details={"existing": list(existing)},
        )

    # Check max participants
    if event.max_participants:
        current_count = event.participants.count()
        if current_count + len(participants_data) > event.max_participants:
            raise CTFValidationError(
                f"Import would exceed maximum participants ({event.max_participants})",
                code="CTF_MAX_PARTICIPANTS_EXCEEDED",
                details={
                    "current": current_count,
                    "importing": len(participants_data),
                    "max": event.max_participants,
                },
            )

    # Create participants
    created: list[CTFParticipant] = []
    now = timezone.now()

    with transaction.atomic():
        for name, email in participants_data:
            participant = CTFParticipant.objects.create(
                event=event,
                email=email,
                name=name,
                status=ParticipantStatus.INVITED.value,
                invited_at=now,
            )
            created.append(participant)

    logger.info(
        "Bulk imported %d participants to event %s",
        len(created),
        event_id,
    )

    return created


def register_participant(
    participant_id: UUID,
    user: User,
    cognito_sub: str | None = None,
) -> CTFParticipant:
    """Register an invited participant with a user account.

    Args:
        participant_id: UUID of the participant record.
        user: The Django user to link.
        cognito_sub: Optional Cognito subject identifier.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFStateError: If participant is already registered.
    """
    logger.info("Registering participant %s with user %s", participant_id, user.email)

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        )

    if participant.user is not None:
        raise CTFStateError(
            "Participant is already registered",
            details={"participant_id": str(participant_id)},
        )

    if not participant.is_invite_valid:
        raise CTFStateError(
            "Invitation has expired",
            details={"participant_id": str(participant_id)},
        )

    with transaction.atomic():
        participant.user = user
        participant.cognito_sub = cognito_sub
        participant.status = ParticipantStatus.REGISTERED.value
        participant.registered_at = timezone.now()
        participant.save(
            update_fields=[
                "user",
                "cognito_sub",
                "status",
                "registered_at",
                "updated_at",
            ]
        )

        logger.info("Registered participant %s", participant_id)

    return participant


def get_participant_by_user(user: User, event_id: UUID | None = None) -> CTFParticipant | None:
    """Get participant record for a user.

    Args:
        user: The Django user.
        event_id: Optional event UUID to filter by.

    Returns:
        The CTFParticipant instance or None.
    """
    qs = CTFParticipant.objects.filter(user=user)
    if event_id:
        qs = qs.filter(event_id=event_id)

    return qs.select_related("event", "team").first()


def disqualify_participant(participant_id: UUID, reason: str | None = None) -> CTFParticipant:
    """Disqualify a participant from the event.

    Args:
        participant_id: UUID of the participant.
        reason: Optional reason for disqualification.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    logger.info("Disqualifying participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        )

    participant.status = ParticipantStatus.DISQUALIFIED.value
    participant.save(update_fields=["status", "updated_at"])

    logger.info(
        "Disqualified participant %s: %s",
        participant_id,
        reason or "No reason provided",
    )

    return participant


def list_participants_for_event(event_id: UUID) -> QuerySet[CTFParticipant]:
    """List all participants for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFParticipant instances.
    """
    return (
        CTFParticipant.objects.filter(event_id=event_id)
        .select_related("team", "user")
        .order_by("name")
    )
