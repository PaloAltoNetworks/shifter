"""CTF Participant service.

Provides business logic for participant management.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant, CTFTeam

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from management.models import UserProfile

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
        ) from None

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
            ) from None

    with transaction.atomic():
        participant = CTFParticipant.objects.create(
            event=event,
            email=email.lower().strip(),
            name=name.strip(),
            team=team,
            status=ParticipantStatus.INVITED.value,
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
        ) from None

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
    for _name, email in participants_data:
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

    with transaction.atomic():
        for name, email in participants_data:
            participant = CTFParticipant.objects.create(
                event=event,
                email=email,
                name=name,
                status=ParticipantStatus.INVITED.value,
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
        ) from None

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

        # Set UserProfile fields so ctf_participant_required decorator works
        # without requiring Cognito custom claims to be pre-configured.
        _set_ctf_participant_profile(user, participant.event)

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
        ) from None

    participant.status = ParticipantStatus.DISQUALIFIED.value
    participant.save(update_fields=["status", "updated_at"])

    # Clear CTF participant profile if user was linked
    if participant.user is not None:
        _clear_ctf_participant_profile(participant.user, participant.event)

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
    return CTFParticipant.objects.filter(event_id=event_id).select_related("team", "user").order_by("name")


def get_participant(participant_id: UUID) -> CTFParticipant:
    """Get a participant by ID.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    try:
        return CTFParticipant.objects.select_related("event", "team", "user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None


def delete_participant(participant_id: UUID) -> bool:
    """Soft delete a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        True if deleted successfully.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    logger.info("Deleting participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    # Clear CTF participant profile if user was linked
    if participant.user is not None:
        _clear_ctf_participant_profile(participant.user, participant.event)

    participant.delete(soft=True)
    logger.info("Deleted participant %s", participant_id)

    return True


def resend_invite(participant_id: UUID) -> CTFParticipant:
    """Resend invitation to a participant and refresh the token.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFStateError: If participant is already registered.
    """
    import secrets
    from datetime import timedelta

    logger.info("Resending invite for participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if participant.is_registered:
        raise CTFStateError(
            "Cannot resend invite to already registered participant",
            details={"participant_id": str(participant_id)},
        )

    # Generate new token with fresh expiry
    now = timezone.now()
    default_expiry = now + timedelta(days=7)
    token_expires = min(default_expiry, participant.event.event_end)

    participant.invite_token = secrets.token_urlsafe(32)
    participant.invite_token_expires = token_expires
    participant.invited_at = now
    participant.save(update_fields=["invite_token", "invite_token_expires", "invited_at", "updated_at"])

    logger.info("Resent invite for participant %s", participant_id)

    return participant


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _set_ctf_participant_profile(user: User, event: CTFEvent) -> UserProfile:
    """Set UserProfile fields for CTF participant access.

    This ensures the ctf_participant_required decorator works without
    requiring Cognito custom claims to be pre-configured externally.
    """
    from management.services import get_user_profile

    profile = get_user_profile(user)
    profile.user_type = "ctf_participant"
    profile.active_ctf_event = event
    profile.save(update_fields=["user_type", "active_ctf_event"])
    logger.info(
        "Set CTF participant profile for user %s (event %s)",
        user.email,
        event.pk,
    )
    return profile


def _clear_ctf_participant_profile(user: User, event: CTFEvent) -> None:
    """Clear CTF participant profile fields on unregister/disqualify/delete.

    Only clears if the profile's active_ctf_event matches the given event,
    to avoid clobbering a profile linked to a different event.
    """
    from management.services import get_user_profile

    profile = get_user_profile(user)
    if profile.active_ctf_event_id == event.pk:
        profile.user_type = "standard"
        profile.active_ctf_event = None
        profile.save(update_fields=["user_type", "active_ctf_event"])
        logger.info(
            "Cleared CTF participant profile for user %s (event %s)",
            user.email,
            event.pk,
        )
