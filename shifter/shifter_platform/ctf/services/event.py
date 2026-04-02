"""CTF Event service.

Provides business logic for CTF event lifecycle management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.enums import VALID_TRANSITIONS, EventStatus, validate_transition
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFEvent

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
        "scoreboard_freeze_at",
    }
)


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
    logger.info("Creating CTF event for user %s", user.email)

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
    logger.info("Updating CTF event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    # Check if event is modifiable
    if not event.is_modifiable:
        raise CTFStateError(
            f"Event cannot be modified in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    # Validate time changes
    new_start = event_data.get("event_start", event.event_start)
    new_end = event_data.get("event_end", event.event_end)
    if new_end <= new_start:
        raise CTFValidationError(
            "Event end must be after event start",
            code="CTF_INVALID_DATES",
        )

    # Filter to allowed fields only — prevent mass assignment of status,
    # created_by, id, timestamps, etc.
    safe_data = {k: v for k, v in event_data.items() if k in _EVENT_MUTABLE_FIELDS}

    with transaction.atomic():
        # Track if we need to reschedule tasks
        schedule_changed = ("event_start" in safe_data and safe_data["event_start"] != event.event_start) or (
            "event_end" in safe_data and safe_data["event_end"] != event.event_end
        )

        # Update only allowed fields
        for key, value in safe_data.items():
            setattr(event, key, value)
        event.save()

        logger.info("Updated CTF event %s", event.id)

        # Reschedule tasks if schedule changed
        if schedule_changed and event.status == EventStatus.REGISTRATION.value:
            _reschedule_event_tasks(event)

    return event


def delete_event(event_id: UUID) -> None:
    """Soft-delete a CTF event.

    Args:
        event_id: UUID of the event to delete.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Deleting CTF event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    with transaction.atomic():
        # Cancel any scheduled tasks
        _cancel_event_tasks(event)

        # Soft delete
        event.delete(soft=True)

        logger.info("Deleted CTF event %s", event_id)


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


def list_events_for_organizer(user: User) -> QuerySet[CTFEvent]:
    """List CTF events created by an organizer.

    Args:
        user: The organizer user.

    Returns:
        QuerySet of CTFEvent instances.
    """
    return CTFEvent.objects.filter(created_by=user).order_by("-event_start")


def start_event(event_id: UUID) -> CTFEvent:
    """Start a CTF event (transition to active).

    Args:
        event_id: UUID of the event.

    Returns:
        The updated CTFEvent instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFStateError: If event cannot be started.
    """
    logger.info("Starting CTF event %s", event_id)

    event = get_event(event_id)

    if event.status != EventStatus.REGISTRATION.value:
        raise CTFStateError(
            f"Cannot start event in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    event.status = EventStatus.ACTIVE.value
    event.save(update_fields=["status", "updated_at"])

    logger.info("Started CTF event %s", event_id)
    return event


def end_event(event_id: UUID) -> CTFEvent:
    """End a CTF event (transition to completed).

    Args:
        event_id: UUID of the event.

    Returns:
        The updated CTFEvent instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFStateError: If event cannot be ended.
    """
    logger.info("Ending CTF event %s", event_id)

    event = get_event(event_id)

    if event.status != EventStatus.ACTIVE.value:
        raise CTFStateError(
            f"Cannot end event in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    event.status = EventStatus.ENDED.value
    event.save(update_fields=["status", "updated_at"])

    logger.info("Ended CTF event %s", event_id)
    return event


def get_organizer_events(
    user: User,
    *,
    status: str | None = None,
) -> QuerySet[CTFEvent]:
    """Get events created by an organizer with optional status filter.

    Args:
        user: The organizer user.
        status: Optional status filter.

    Returns:
        QuerySet of CTFEvent instances.
    """
    queryset = CTFEvent.objects.filter(created_by=user)

    if status:
        queryset = queryset.filter(status=status)

    return queryset.order_by("-event_start")


def schedule_event(event: CTFEvent) -> bool:
    """Open registration for a draft event (transition to registration).

    Args:
        event: The CTFEvent to open registration for.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Opening registration for CTF event %s", event.id)

    try:
        _transition_event(event, EventStatus.REGISTRATION)
    except CTFStateError:
        logger.warning(
            "Cannot open registration for event %s: not in draft state (current: %s)",
            event.id,
            event.status,
        )
        return False

    _schedule_event_tasks(event)

    logger.info("Opened registration for CTF event %s", event.id)
    return True


# Alias with clearer name
open_registration = schedule_event


def activate_event(event: CTFEvent) -> bool:
    """Activate a registration event (transition to active).

    For resuming a paused event, use ``resume_event`` instead.

    Args:
        event: The CTFEvent to activate.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Activating CTF event %s", event.id)

    if event.status != EventStatus.REGISTRATION.value:
        logger.warning(
            "Cannot activate event %s: not in registration state (current: %s)",
            event.id,
            event.status,
        )
        return False

    try:
        _transition_event(event, EventStatus.ACTIVE)
    except CTFStateError:
        return False

    logger.info("Activated CTF event %s", event.id)
    return True


def complete_event(event: CTFEvent) -> bool:
    """End an active event (transition to ended).

    If ``auto_cleanup`` is enabled, destroys all participant ranges
    to prevent orphaned cloud resources.

    Args:
        event: The CTFEvent to end.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Ending CTF event %s", event.id)

    try:
        _transition_event(event, EventStatus.ENDED)
    except CTFStateError:
        logger.warning(
            "Cannot end event %s: not in active state (current: %s)",
            event.id,
            event.status,
        )
        return False

    if event.auto_cleanup:
        from ctf.services.range import cleanup_event_ranges

        result = cleanup_event_ranges(event.pk)
        logger.info("Auto-cleanup on event end %s: %s", event.id, result)

    logger.info("Ended CTF event %s", event.id)
    return True


def get_event_stats(event: CTFEvent) -> dict:
    """Get statistics for an event.

    Args:
        event: The event to get stats for.

    Returns:
        Dictionary with event statistics.
    """
    from django.db.models import Sum

    from ctf.enums import ParticipantStatus
    from ctf.models import CTFSubmission

    stats = {
        "participant_count": event.participants.count(),
        "registered_count": event.participants.filter(
            status__in=[
                ParticipantStatus.REGISTERED.value,
                ParticipantStatus.ACTIVE.value,
                ParticipantStatus.COMPLETED.value,
            ]
        ).count(),
        "invited_count": event.participants.filter(status=ParticipantStatus.INVITED.value).count(),
        "challenge_count": event.challenges.count(),
        "team_count": event.teams.count() if event.team_mode else 0,
        "total_submissions": CTFSubmission.objects.filter(participant__event=event).count(),
        "correct_submissions": CTFSubmission.objects.filter(
            participant__event=event,
            is_correct=True,
        ).count(),
    }

    # Calculate total possible points
    points_result = event.challenges.aggregate(total=Sum("points"))
    stats["total_points"] = points_result["total"] or 0

    return stats


def cancel_event(event: CTFEvent) -> bool:
    """Cancel a CTF event.

    Cancellation is valid from draft, registration, active, or paused states.
    Always destroys all participant ranges to prevent orphaned cloud resources.

    Args:
        event: The CTFEvent to cancel.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Cancelling CTF event %s", event.id)

    try:
        with transaction.atomic():
            _transition_event(event, EventStatus.CANCELLED)
            _cancel_event_tasks(event)
    except CTFStateError:
        logger.warning(
            "Cannot cancel event %s: in terminal state %s",
            event.id,
            event.status,
        )
        return False

    # Always destroy ranges on cancel — orphaned VMs waste money
    from ctf.services.range import cleanup_event_ranges

    result = cleanup_event_ranges(event.pk)
    logger.info("Range cleanup on event cancel %s: %s", event.id, result)

    logger.info("Cancelled CTF event %s", event.id)
    return True


def pause_event(event: CTFEvent) -> bool:
    """Pause an active event (transition to paused).

    Submissions are not accepted while paused.

    Args:
        event: The CTFEvent to pause.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Pausing CTF event %s", event.id)

    try:
        _transition_event(event, EventStatus.PAUSED)
    except CTFStateError:
        logger.warning(
            "Cannot pause event %s: not in active state (current: %s)",
            event.id,
            event.status,
        )
        return False

    logger.info("Paused CTF event %s", event.id)
    return True


def resume_event(event: CTFEvent) -> bool:
    """Resume a paused event (transition back to active).

    Args:
        event: The CTFEvent to resume.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Resuming CTF event %s", event.id)

    try:
        _transition_event(event, EventStatus.ACTIVE)
    except CTFStateError:
        logger.warning(
            "Cannot resume event %s: not in paused state (current: %s)",
            event.id,
            event.status,
        )
        return False

    logger.info("Resumed CTF event %s", event.id)
    return True


def archive_event(event: CTFEvent) -> bool:
    """Archive an ended event (transition to archived).

    Args:
        event: The CTFEvent to archive.

    Returns:
        True if transition succeeded, False otherwise.
    """
    logger.info("Archiving CTF event %s", event.id)

    try:
        _transition_event(event, EventStatus.ARCHIVED)
    except CTFStateError:
        logger.warning(
            "Cannot archive event %s: not in ended state (current: %s)",
            event.id,
            event.status,
        )
        return False

    logger.info("Archived CTF event %s", event.id)
    return True


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _transition_event(event: CTFEvent, target: EventStatus) -> None:
    """Perform a validated state transition.

    Args:
        event: The event to transition.
        target: The target status.

    Raises:
        CTFStateError: If the transition is invalid.
    """
    try:
        current = EventStatus(event.status)
    except ValueError:
        raise CTFStateError(
            f"Unknown event status: {event.status}",
            details={"event_id": str(event.id), "status": event.status},
        ) from None

    if not validate_transition(current, target):
        raise CTFStateError(
            f"Cannot transition from {current.value} to {target.value}",
            details={
                "event_id": str(event.id),
                "current_status": current.value,
                "target_status": target.value,
                "valid_targets": [s.value for s in VALID_TRANSITIONS.get(current, frozenset())],
            },
        )

    event.status = target.value
    event.save(update_fields=["status", "updated_at"])


def _schedule_event_tasks(event: CTFEvent) -> None:
    """Schedule automated tasks for an event.

    Tasks are recorded in the database and executed by the
    ``run_ctf_scheduler`` management command.
    """
    from datetime import timedelta

    from django.utils import timezone

    from ctf.enums import ScheduledTaskType
    from ctf.models import CTFScheduledTask

    now = timezone.now()

    # Spin up ranges before event
    CTFScheduledTask.objects.create(
        event=event,
        task_type=ScheduledTaskType.SPIN_UP_RANGES.value,
        scheduled_for=event.get_spinup_time(),
    )

    # Event start
    CTFScheduledTask.objects.create(
        event=event,
        task_type=ScheduledTaskType.EVENT_START.value,
        scheduled_for=event.event_start,
    )

    # Event end
    CTFScheduledTask.objects.create(
        event=event,
        task_type=ScheduledTaskType.EVENT_END.value,
        scheduled_for=event.event_end,
    )

    # Cleanup ranges after event (if auto_cleanup)
    if event.auto_cleanup:
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.CLEANUP_RANGES.value,
            scheduled_for=event.get_cleanup_time(),
        )

    # Send reminder 24h before start (if that's still in the future)
    reminder_time = event.event_start - timedelta(hours=24)
    if reminder_time > now:
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.SEND_REMINDER.value,
            scheduled_for=reminder_time,
        )

    logger.info("Scheduled tasks for event %s", event.id)


def _reschedule_event_tasks(event: CTFEvent) -> None:
    """Reschedule tasks after event times change."""
    _cancel_event_tasks(event)
    _schedule_event_tasks(event)
    _reschedule_challenge_release_tasks(event)
    logger.info("Rescheduled tasks for event %s", event.id)


def _reschedule_challenge_release_tasks(event: CTFEvent) -> None:
    """Recreate RELEASE_CHALLENGE tasks for all eligible challenges in the event."""
    from ctf.enums import ChallengeVisibility
    from ctf.models import CTFChallenge
    from ctf.services.challenge import _sync_release_task

    challenges = CTFChallenge.objects.filter(
        event=event,
        visibility=ChallengeVisibility.HIDDEN.value,
        release_time__isnull=False,
        deleted_at__isnull=True,
    )
    for challenge in challenges:
        _sync_release_task(challenge)


def _cancel_event_tasks(event: CTFEvent) -> None:
    """Cancel all scheduled tasks for an event.

    Args:
        event: The CTFEvent to cancel tasks for.
    """
    from ctf.enums import ScheduledTaskStatus
    from ctf.models import CTFScheduledTask

    pending_tasks = CTFScheduledTask.objects.filter(
        event=event,
        status=ScheduledTaskStatus.PENDING.value,
    )

    cancelled_count = 0
    for task in pending_tasks:
        task.mark_cancelled()
        cancelled_count += 1

    if cancelled_count:
        logger.info("Cancelled %d scheduled tasks for event %s", cancelled_count, event.id)
