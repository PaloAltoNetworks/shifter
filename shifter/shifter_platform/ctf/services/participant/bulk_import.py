"""Bulk participant CSV import (CTF-603).

Per-row failures never sink the import: valid rows are created, bad rows are
reported individually (format problems, duplicates within the file, and
duplicates against existing registrations). Event-level problems — unknown
event, closed registration window, capacity — still fail the whole call.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any
from uuid import UUID

from django.db import transaction

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.participant.lifecycle import _auto_register_participant
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def _validate_row(row: list[str], line_num: int, seen_emails: set[str]) -> tuple[str, str] | str:
    """Validate one CSV row; return (name, email) or a human-readable error."""
    if len(row) < 2:
        return f"Line {line_num}: Expected name,email format"
    name = row[0].strip()
    email = row[1].strip().lower()
    error = None
    if not name:
        error = f"Line {line_num}: Name is required"
    elif email and "@" not in email:
        error = f"Line {line_num}: Invalid email format"
    elif email and email in seen_emails:
        error = f"Line {line_num}: Duplicate email within file ({email})"
    return error if error is not None else (name, email)


def _parse_participants_csv(csv_content: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse a CSV string into (name, email) tuples plus per-row error notes.

    Empty rows are skipped. A row failing validation is reported and dropped;
    parsing never raises for row-level problems (CTF-603). Duplicate emails
    within the file keep the first occurrence.
    """
    reader = csv.reader(io.StringIO(csv_content))
    participants_data: list[tuple[str, str]] = []
    errors: list[str] = []
    seen_emails: set[str] = set()
    for line_num, row in enumerate(reader, start=1):
        if not row or (len(row) == 1 and not row[0].strip()):
            continue
        validated = _validate_row(row, line_num, seen_emails)
        if isinstance(validated, str):
            errors.append(validated)
            continue
        name, email = validated
        if email:
            seen_emails.add(email)
        participants_data.append((name, email))
    return participants_data, errors


def _assert_event_accepts_import(event: CTFEvent, importing: int) -> None:
    """Reject the import if it would exceed the participant cap.

    CTF-705: the registration deadline closes self-registration only;
    organizer-driven import stays open so stragglers can join a live event.
    """
    if not event.max_participants:
        return
    current_count = event.participants.count()
    if current_count + importing > event.max_participants:
        raise CTFValidationError(
            f"Import would exceed maximum participants ({event.max_participants})",
            code="CTF_MAX_PARTICIPANTS_EXCEEDED",
            details={
                "current": current_count,
                "importing": importing,
                "max": event.max_participants,
            },
        )


def bulk_import_participants(
    event_id: UUID,
    csv_content: str,
) -> dict[str, Any]:
    """Bulk import participants from CSV content (``name,email`` per line).

    Args:
        event_id: UUID of the event.
        csv_content: CSV string with participant data.

    Returns:
        Dict with ``created`` (list of new ``CTFParticipant`` rows) and
        ``errors`` (per-row human-readable notes for every skipped row).

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFValidationError: For event-level failures (deadline, capacity).
    """
    logger.info("Bulk importing participants to event %s", safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants_data, errors = _parse_participants_csv(csv_content)

    created: list[CTFParticipant] = []
    with transaction.atomic():
        # Lock the event so the capacity check and the inserts cannot race past
        # max_participants under concurrent imports (#1145).
        CTFEvent.objects.select_for_update().get(pk=event.pk)
        # CTF-601: emails already registered for this event are per-row skips,
        # resolved under the lock so a concurrent import cannot double-insert.
        existing_emails = set(
            event.participants.exclude(email="").values_list("email", flat=True),
        )
        importable: list[tuple[str, str]] = []
        for name, email in participants_data:
            if email and email in existing_emails:
                errors.append(f"{email}: already registered for this event")
                continue
            importable.append((name, email))
        _assert_event_accepts_import(event, len(importable))
        for name, email in importable:
            participant = CTFParticipant.objects.create(
                event=event,
                email=email,
                name=name,
                status=ParticipantStatus.INVITED.value,
            )
            _auto_register_participant(participant)
            created.append(participant)

    logger.info(
        "Bulk imported %d participants to event %s (%d rows skipped)",
        len(created),
        safe_log_value(event_id),
        len(errors),
    )
    return {"created": created, "errors": errors}
