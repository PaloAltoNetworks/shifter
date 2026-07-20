"""CTF Event CRUD: create, read, update, delete, and force-delete.

``_cancel_event_tasks`` is resolved through the ``ctf.services.event``
package at call time (``from ctf.services import event as _e``) rather than
imported directly, so ``unittest.mock.patch`` targets of the form
``patch("ctf.services.event._cancel_event_tasks")`` keep working after the
package split -- see the package ``__init__`` docstring for the full
rationale.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.enums import EventStatus
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFEvent
from shared.log_sanitize import safe_log_value

from .scheduling import _reschedule_event_tasks, _reschedule_live_event_schedule

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# Fields that organizers may set when creating or updating events.
# All other fields (status, created_by, id, timestamps, etc.) are
# controlled internally and must not be overwritten by user input.
_EVENT_MUTABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "event_start",
        "event_end",
        "registration_deadline",
        "scenario_id",
        "auto_cleanup",
        "cleanup_delay_hours",
        "max_participants",
        "team_mode",
        "team_size_limit",
        "range_spinup_minutes",
        "range_config",
        "submission_cooldown_seconds",
        "attempt_limit_mode",
        "attempt_limit_cooldown_seconds",
        "rating_visibility",
        "scoreboard_visibility",
        "scoreboard_freeze_at",
        "scoring_mode",
        "rules",
        "reminder_hours",
        "event_timezone",
        "capacity_hints",
        "logo_url",
        "visible_os_types",
        "theme_color",
    }
)


def _validate_scoring_mode(event_data: dict[str, Any]) -> None:
    """Reject an unknown ``scoring_mode`` with a controlled 400.

    The model field constrains choices, but the JSON API path bypasses form
    validation, so validate here to surface a `CTFValidationError` (400) rather
    than persisting an invalid value that would later fall back to standard.
    """
    from ctf.enums import ScoringMode
    from ctf.extensions import registered_scoring_modes

    if "scoring_mode" not in event_data:
        return
    if event_data["scoring_mode"] in registered_scoring_modes():
        return
    try:
        ScoringMode(event_data["scoring_mode"])
    except ValueError:
        raise CTFValidationError(
            "Invalid scoring mode",
            code="CTF_INVALID_SCORING_MODE",
            details={
                "scoring_mode": event_data["scoring_mode"],
                "valid_modes": [m.value for m in ScoringMode],
            },
        ) from None


def create_event(user: User, event_data: dict[str, Any]) -> CTFEvent:
    """Create a new CTF event.

    Args:
        user: The user creating the event (becomes created_by).
        event_data: Dictionary containing event fields.

    Returns:
        The created CTFEvent instance.

    Raises:
        CTFValidationError: If event data is invalid.
    """
    logger.info("Creating CTF event for user %s", safe_log_value(user.email))

    # Validate required fields
    required_fields = ["name", "event_start", "event_end"]
    missing = [f for f in required_fields if f not in event_data]
    if missing:
        raise CTFValidationError(
            f"Missing required fields: {', '.join(missing)}",
            details={"missing_fields": missing},
        )

    # Validate event times
    event_start = event_data.get("event_start")
    event_end = event_data.get("event_end")
    if event_start and event_end and event_end <= event_start:
        raise CTFValidationError(
            "Event end must be after event start",
            code="CTF_INVALID_DATES",
        )

    _validate_scoring_mode(event_data)

    # Filter to allowed fields only — prevent mass assignment of status,
    # created_by, id, timestamps, etc.
    safe_data = {k: v for k, v in event_data.items() if k in _EVENT_MUTABLE_FIELDS}

    with transaction.atomic():
        event = CTFEvent.objects.create(
            created_by=user,
            status=EventStatus.DRAFT.value,
            **safe_data,
        )

        logger.info("Created CTF event %s: %s", event.id, event.name)

    return event


def _validate_event_time_range(event_start: datetime, event_end: datetime) -> None:
    """Raise when event_end is not strictly after event_start."""
    if event_end <= event_start:
        raise CTFValidationError(
            "Event end must be after event start",
            code="CTF_INVALID_DATES",
        )


def _reschedule_event_if_schedule_changed(
    event: CTFEvent,
    safe_data: dict[str, Any],
    *,
    old_event_start: datetime,
    old_event_end: datetime,
    old_cleanup_time: datetime | None,
) -> None:
    """Reschedule pending tasks when event times change."""
    schedule_changed = ("event_start" in safe_data and safe_data["event_start"] != old_event_start) or (
        "event_end" in safe_data and safe_data["event_end"] != old_event_end
    )
    event_end_changed = "event_end" in safe_data and safe_data["event_end"] != old_event_end
    if schedule_changed and event.status == EventStatus.REGISTRATION.value:
        _reschedule_event_tasks(event)
    elif event_end_changed and event.status in (
        EventStatus.ACTIVE.value,
        EventStatus.PAUSED.value,
    ):
        _reschedule_live_event_schedule(event)
    if old_cleanup_time is not None and event.get_cleanup_time() != old_cleanup_time:
        from ctf.services._event_range_lease import reconcile_event_range_leases

        reconcile_event_range_leases(event)


_TEAM_CONFIG_FIELDS = frozenset({"team_mode", "team_size_limit"})


def _reject_team_config_changes_after_start(event: CTFEvent, event_data: dict[str, Any]) -> None:
    """CTF-501: team mode and size are structural — frozen once the event starts.

    Changing them mid-competition would strand existing teams or silently
    invalidate the capacity guard, so edits are allowed only in DRAFT and
    REGISTRATION (values equal to the current ones pass through unchanged).
    """
    if event.status in (EventStatus.DRAFT.value, EventStatus.REGISTRATION.value):
        return
    changed = {
        field for field in _TEAM_CONFIG_FIELDS if field in event_data and event_data[field] != getattr(event, field)
    }
    if changed:
        raise CTFStateError(
            "Team settings cannot change after the event starts",
            details={"event_status": event.status, "fields": sorted(changed)},
        )


def update_event(event_id: UUID, event_data: dict[str, Any]) -> CTFEvent:
    """Update an existing CTF event.

    Args:
        event_id: UUID of the event to update.
        event_data: Dictionary containing fields to update.

    Returns:
        The updated CTFEvent instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFStateError: If event is not modifiable.
        CTFValidationError: If event data is invalid.
    """
    logger.info("Updating CTF event %s", safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    _reject_team_config_changes_after_start(event, event_data)

    # Check if event is modifiable
    if not event.is_modifiable:
        raise CTFStateError(
            f"Event cannot be modified in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    new_start = event_data.get("event_start", event.event_start)
    new_end = event_data.get("event_end", event.event_end)
    _validate_event_time_range(new_start, new_end)
    _validate_scoring_mode(event_data)

    safe_data = {k: v for k, v in event_data.items() if k in _EVENT_MUTABLE_FIELDS}
    old_event_start = event.event_start
    old_event_end = event.event_end
    cleanup_may_change = bool({"event_end", "cleanup_delay_hours"} & safe_data.keys())
    old_cleanup_time = event.get_cleanup_time() if cleanup_may_change else None

    with transaction.atomic():
        for key, value in safe_data.items():
            setattr(event, key, value)
        event.save()

        logger.info("Updated CTF event %s", event.id)
        _reschedule_event_if_schedule_changed(
            event,
            safe_data,
            old_event_start=old_event_start,
            old_event_end=old_event_end,
            old_cleanup_time=old_cleanup_time,
        )

    return event


def delete_event(event_id: UUID) -> None:
    """Soft-delete a CTF event.

    Args:
        event_id: UUID of the event to delete.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Deleting CTF event %s", safe_log_value(event_id))

    from ctf.services import event as _e

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    with transaction.atomic():
        # Cancel any scheduled tasks
        _e._cancel_event_tasks(event)

        # Soft delete
        event.delete(soft=True)

        logger.info("Deleted CTF event %s", safe_log_value(event_id))


def force_delete_event(
    event_id: UUID,
    actor: User,
    confirmation_name: str,
) -> dict[str, Any]:
    """Force-delete a CTF event and all associated resources.

    Permanently removes the event regardless of its current state. All child
    records (challenges, participants, submissions, scores, scheduled tasks,
    etc.) are cascade-deleted. Range instances are destroyed first via the CMS
    bridge.

    Args:
        event_id: UUID of the event to force-delete.
        actor: The user performing the deletion.
        confirmation_name: Must match the event name exactly (case-sensitive).

    Returns:
        Summary dict with event_id, event_name, ranges_destroyed, ranges_failed.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFValidationError: If confirmation_name doesn't match.
    """
    from ctf.models import CTFChallengeFile, CTFParticipant
    from ctf.s3 import delete_challenge_file
    from ctf.services import event as _e
    from ctf.services.range.lifecycle import _destroy_single_range

    # Use all_objects so force delete works on soft-deleted events too
    try:
        event = CTFEvent.all_objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    if confirmation_name != event.name:
        raise CTFValidationError(
            "Confirmation name does not match event name",
            details={
                "expected": event.name,
                "provided": confirmation_name,
            },
        )

    event_name = event.name

    # Destroy range instances OUTSIDE the atomic block (external HTTP calls).
    # Query participants directly via all_objects to handle soft-deleted events
    # (cleanup_event_ranges uses CTFEvent.objects which skips soft-deleted).
    ranges_destroyed = 0
    ranges_failed = 0
    participants_with_ranges = CTFParticipant.all_objects.filter(
        event=event,
        range_instance_id__isnull=False,
    ).select_related("user")
    for participant in participants_with_ranges:
        try:
            _destroy_single_range(participant, participant.user)
            ranges_destroyed += 1
        except Exception:
            ranges_failed += 1
            logger.exception(
                "Failed to destroy range for participant %s during force delete",
                participant.pk,
            )

    # Delete S3 challenge file blobs before cascade removes the DB rows
    s3_keys = list(
        CTFChallengeFile.all_objects.filter(
            challenge__event=event,
        ).values_list("s3_key", flat=True)
    )
    for s3_key in s3_keys:
        try:
            delete_challenge_file(s3_key)
        except Exception:
            logger.exception("Failed to delete S3 object %s during force delete", s3_key)

    # Hard delete inside atomic block — Django CASCADE handles children
    with transaction.atomic():
        _e._cancel_event_tasks(event)
        event.delete(soft=False)

    logger.warning(
        "FORCE DELETE: Event %s (%s) permanently deleted by %s (pk=%s). Ranges destroyed: %d, ranges failed: %d.",
        safe_log_value(event_id),
        safe_log_value(event_name),
        safe_log_value(actor.email),
        actor.pk,
        ranges_destroyed,
        ranges_failed,
    )

    return {
        "event_id": str(event_id),
        "event_name": event_name,
        "ranges_destroyed": ranges_destroyed,
        "ranges_failed": ranges_failed,
    }


def get_event(event_id: UUID) -> CTFEvent:
    """Get a CTF event by ID.

    Args:
        event_id: UUID of the event.

    Returns:
        The CTFEvent instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    try:
        return CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None


def event_pk_if_exists(event_id: UUID) -> UUID | None:
    """Return the event's primary key if it exists, else ``None``.

    Bounded existence check for cross-domain composition (``config``) that must
    validate a CTF event id without importing the ``ctf`` domain model. Returns a
    primitive, never an ORM object (ADR-001, #1523).
    """
    pk = CTFEvent.objects.filter(pk=event_id).values_list("pk", flat=True).first()
    return pk


def list_events_for_organizer(user: User) -> QuerySet[CTFEvent]:
    """List CTF events created by an organizer.

    Args:
        user: The organizer user.

    Returns:
        QuerySet of CTFEvent instances.
    """
    return CTFEvent.objects.filter(created_by=user).order_by("-event_start")
