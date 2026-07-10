"""Bulk participant CSV import."""

from __future__ import annotations

import csv
import io
import logging
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.participant.lifecycle import _auto_register_participant
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def _parse_participants_csv(csv_content: str) -> list[tuple[str, str]]:
    """Parse a CSV string into (name, email) tuples; raise on per-row errors.

    Empty rows are skipped. Per-row failures are accumulated and reported in
    one `CTFValidationError` so the caller can present every issue at once.
    """
    reader = csv.reader(io.StringIO(csv_content))
    participants_data: list[tuple[str, str]] = []
    errors: list[str] = []
    for line_num, row in enumerate(reader, start=1):
        if not row or (len(row) == 1 and not row[0].strip()):
            continue
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
    return participants_data


def _emails_or_raise_on_duplicate(participants_data: list[tuple[str, str]]) -> set[str]:
    """Return the set of unique emails; raise if any duplicate appears in input."""
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
    return seen_emails


def _assert_event_accepts_import(event: CTFEvent, participants_data: list[tuple[str, str]]) -> None:
    """Reject the import if the event is past deadline or would exceed cap."""
    if event.registration_deadline and timezone.now() > event.registration_deadline:
        raise CTFValidationError(
            "Registration deadline has passed",
            code="CTF_REGISTRATION_DEADLINE_PASSED",
            details={
                "event_id": str(event.pk),
                "deadline": event.registration_deadline.isoformat(),
            },
        )
    if not event.max_participants:
        return
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
    logger.info("Bulk importing participants to event %s", safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants_data = _parse_participants_csv(csv_content)
    seen_emails = _emails_or_raise_on_duplicate(participants_data)
    # Capacity is asserted under the event row lock inside the transaction
    # below (#1145), so concurrent imports cannot race past max_participants.

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

    created: list[CTFParticipant] = []
    with transaction.atomic():
        # Lock the event so the capacity assert and the inserts cannot race past
        # max_participants under concurrent imports (#1145).
        CTFEvent.objects.select_for_update().get(pk=event.pk)
        _assert_event_accepts_import(event, participants_data)
        for name, email in participants_data:
            participant = CTFParticipant.objects.create(
                event=event,
                email=email,
                name=name,
                status=ParticipantStatus.INVITED.value,
            )
            _auto_register_participant(participant)
            created.append(participant)

    logger.info(
        "Bulk imported %d participants to event %s",
        len(created),
        safe_log_value(event_id),
    )
    return created
