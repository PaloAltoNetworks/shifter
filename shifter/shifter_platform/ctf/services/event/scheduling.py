"""Scheduled-task management for CTF event lifecycle automation."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from ctf.enums import ScheduledTaskType
from ctf.models import CTFEvent, CTFScheduledTask
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

# Lead time between the participant cleanup warning and range destruction.
_CLEANUP_WARNING_LEAD_MINUTES = 30


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

    # Cleanup ranges after event (if auto_cleanup), preceded by a participant
    # warning so nobody loses in-progress work without notice (CTF-1003).
    if event.auto_cleanup:
        cleanup_time = event.get_cleanup_time()
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.CLEANUP_RANGES.value,
            scheduled_for=cleanup_time,
        )
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.CLEANUP_WARNING.value,
            scheduled_for=max(event.event_end, cleanup_time - timedelta(minutes=_CLEANUP_WARNING_LEAD_MINUTES)),
        )

    # Schedule reminders at configurable intervals before event start
    reminder_intervals = [h for h in (event.reminder_hours or [24, 1]) if isinstance(h, int) and h > 0]
    for hours in reminder_intervals:
        reminder_time = event.event_start - timedelta(hours=hours)
        if reminder_time > now:
            CTFScheduledTask.objects.create(
                event=event,
                task_type=ScheduledTaskType.SEND_REMINDER.value,
                scheduled_for=reminder_time,
                metadata={"hours_before": hours},
            )

    logger.info("Scheduled tasks for event %s", event.id)


def _reschedule_live_event_schedule(event: CTFEvent) -> None:
    """Reschedule pending end-of-life tasks after event_end moves during a live event."""
    from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
    from ctf.models import CTFScheduledTask

    for task in CTFScheduledTask.objects.filter(
        event=event,
        task_type=ScheduledTaskType.EVENT_END.value,
        status=ScheduledTaskStatus.PENDING.value,
    ):
        task.mark_cancelled()

    CTFScheduledTask.objects.create(
        event=event,
        task_type=ScheduledTaskType.EVENT_END.value,
        scheduled_for=event.event_end,
    )

    for task in CTFScheduledTask.objects.filter(
        event=event,
        task_type__in=[ScheduledTaskType.CLEANUP_RANGES.value, ScheduledTaskType.CLEANUP_WARNING.value],
        status=ScheduledTaskStatus.PENDING.value,
    ):
        task.mark_cancelled()

    if event.auto_cleanup:
        cleanup_time = event.get_cleanup_time()
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.CLEANUP_RANGES.value,
            scheduled_for=cleanup_time,
        )
        CTFScheduledTask.objects.create(
            event=event,
            task_type=ScheduledTaskType.CLEANUP_WARNING.value,
            scheduled_for=max(event.event_end, cleanup_time - timedelta(minutes=_CLEANUP_WARNING_LEAD_MINUTES)),
        )

    logger.info("Rescheduled live end tasks for event %s", event.id)


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

    # CTFChallenge.objects is a SoftDeleteManager, so deleted rows are
    # already excluded by default — no inline deleted_at filter needed.
    challenges = CTFChallenge.objects.filter(
        event=event,
        visibility=ChallengeVisibility.HIDDEN.value,
        release_time__isnull=False,
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


def list_event_tasks(event_id: UUID) -> QuerySet[CTFScheduledTask]:
    """Organizer-facing scheduled task history for one event (#526)."""
    return CTFScheduledTask.objects.filter(event_id=event_id, deleted_at__isnull=True).order_by(
        "scheduled_for", "created_at"
    )


def run_task_now(event_id: UUID, task_id: UUID) -> CTFScheduledTask:
    """Make a pending task due immediately (#526 manual trigger).

    The scheduler's normal claim path executes it on the next poll, so manual
    runs get exactly the same locking, retry, and logging as automatic ones.
    """
    from ctf.enums import ScheduledTaskStatus
    from ctf.exceptions import CTFNotFoundError, CTFStateError

    task = CTFScheduledTask.objects.filter(pk=task_id, event_id=event_id, deleted_at__isnull=True).first()
    if task is None:
        raise CTFNotFoundError("Scheduled task not found", details={"task_id": str(task_id)})
    if task.status != ScheduledTaskStatus.PENDING.value:
        raise CTFStateError(
            "Only pending tasks can be run now",
            details={"task_id": str(task_id), "status": task.status},
        )
    task.scheduled_for = timezone.now()
    task.save(update_fields=["scheduled_for", "updated_at"])
    logger.info("Task %s (%s) made due now for event %s", task.pk, task.task_type, safe_log_value(event_id))
    return task


def _pending_cleanup_tasks(event_id: UUID) -> QuerySet[CTFScheduledTask]:
    """Pending cleanup + warning rows for one event."""
    from ctf.enums import ScheduledTaskStatus

    return CTFScheduledTask.objects.filter(
        event_id=event_id,
        task_type__in=[ScheduledTaskType.CLEANUP_RANGES.value, ScheduledTaskType.CLEANUP_WARNING.value],
        status=ScheduledTaskStatus.PENDING.value,
        deleted_at__isnull=True,
    )


def has_pending_cleanup_task(event_id: UUID) -> bool:
    """Whether a delayed CLEANUP_RANGES task still owns this event's teardown."""
    from ctf.enums import ScheduledTaskStatus

    return CTFScheduledTask.objects.filter(
        event_id=event_id,
        task_type=ScheduledTaskType.CLEANUP_RANGES.value,
        status=ScheduledTaskStatus.PENDING.value,
        deleted_at__isnull=True,
    ).exists()


def defer_event_cleanup(event_id: UUID, hours: int) -> int:
    """Push the pending automated cleanup (and its warning) back by `hours` (CTF-1003).

    Returns the number of tasks moved; raises when no cleanup is pending.
    """
    from ctf.exceptions import CTFStateError, CTFValidationError

    if not 1 <= hours <= 168:
        raise CTFValidationError(
            "Deferral must be between 1 and 168 hours",
            code="CTF_INVALID_CLEANUP_DEFERRAL",
            details={"hours": hours},
        )
    tasks = list(_pending_cleanup_tasks(event_id))
    if not tasks:
        raise CTFStateError("No pending cleanup to defer", details={"event_id": str(event_id)})
    for task in tasks:
        task.scheduled_for = task.scheduled_for + timedelta(hours=hours)
        task.save(update_fields=["scheduled_for", "updated_at"])
    logger.info("Deferred cleanup for event %s by %d hours (%d tasks)", safe_log_value(event_id), hours, len(tasks))
    return len(tasks)


def cancel_event_cleanup(event_id: UUID) -> int:
    """Cancel the pending automated cleanup (and its warning) (CTF-1003).

    Ranges then live until the organizer destroys them or force-deletes the
    event. Returns the number of tasks cancelled; raises when none pend.
    """
    from ctf.exceptions import CTFStateError

    tasks = list(_pending_cleanup_tasks(event_id))
    if not tasks:
        raise CTFStateError("No pending cleanup to cancel", details={"event_id": str(event_id)})
    for task in tasks:
        task.mark_cancelled()
    logger.info("Cancelled automated cleanup for event %s (%d tasks)", safe_log_value(event_id), len(tasks))
    return len(tasks)
