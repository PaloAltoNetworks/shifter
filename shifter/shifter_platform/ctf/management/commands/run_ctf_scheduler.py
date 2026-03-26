"""CTF scheduled task executor.

Polls for due CTFScheduledTask rows and dispatches them to the appropriate
handler. Follows the same signal-handling and heartbeat pattern as
shared/management/commands/run_worker.py.

Usage:
    python manage.py run_ctf_scheduler
    python manage.py run_ctf_scheduler --poll-interval 15 --batch-size 5

Health monitoring:
    Touches /tmp/ctf-scheduler-heartbeat after each poll cycle.
"""

from __future__ import annotations

import contextlib
import logging
import signal
import tempfile
import time
from argparse import ArgumentParser
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
from ctf.models import CTFScheduledTask

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "ctf-scheduler-heartbeat"

# Tasks running longer than this are considered stale and marked FAILED.
STALE_TASK_MINUTES = 30


class Command(BaseCommand):
    """Poll and execute due CTF scheduled tasks."""

    help = "Run the CTF scheduled task executor"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown = False

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=30,
            help="Seconds between poll cycles (default: 30)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Max tasks to fetch per cycle (default: 10)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        poll_interval = options["poll_interval"]
        batch_size = options["batch_size"]

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(
            "CTF scheduler starting: poll_interval=%ds batch_size=%d",
            poll_interval,
            batch_size,
        )

        while not self.shutdown:
            try:
                self._recover_stale_tasks()
                tasks = self._fetch_due_tasks(batch_size)
                for task in tasks:
                    if self.shutdown:
                        break
                    self._execute_task(task)
            except Exception:
                logger.exception("Error in CTF scheduler poll cycle")

            self._touch_heartbeat()

            # Sleep in short increments so we respond to signals quickly
            for _ in range(poll_interval):
                if self.shutdown:
                    break
                time.sleep(1)

        self._cleanup_heartbeat()
        logger.info("CTF scheduler shutdown complete")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("CTF scheduler received %s, shutting down", sig_name)
        self.shutdown = True

    def _fetch_due_tasks(self, batch_size: int) -> list[CTFScheduledTask]:
        """Fetch and atomically claim due tasks."""
        with transaction.atomic():
            tasks = list(
                CTFScheduledTask.objects.select_for_update(skip_locked=True)
                .filter(
                    status=ScheduledTaskStatus.PENDING.value,
                    scheduled_for__lte=timezone.now(),
                )
                .order_by("scheduled_for")[:batch_size]
            )
            for task in tasks:
                task.mark_running()
        return tasks

    def _recover_stale_tasks(self) -> None:
        """Mark RUNNING tasks older than STALE_TASK_MINUTES as FAILED."""
        cutoff = timezone.now() - timedelta(minutes=STALE_TASK_MINUTES)
        stale = CTFScheduledTask.objects.filter(
            status=ScheduledTaskStatus.RUNNING.value,
            updated_at__lt=cutoff,
        )
        for task in stale:
            task.mark_failed(f"Stale: running for over {STALE_TASK_MINUTES} minutes")
            logger.warning("Recovered stale task %s (%s)", task.pk, task.task_type)

    def _execute_task(self, task: CTFScheduledTask) -> None:
        """Dispatch a task to its handler and record the outcome."""
        logger.info(
            "Executing task %s: type=%s event=%s",
            task.pk,
            task.task_type,
            task.event_id,
        )
        try:
            handler = TASK_HANDLERS.get(task.task_type)
            if handler is None:
                raise ValueError(f"No handler for task type: {task.task_type}")
            handler(task, shutdown_check=lambda: self.shutdown)
            task.mark_completed()
        except Exception as exc:
            logger.exception("Task %s failed: %s", task.pk, exc)
            task.mark_failed(str(exc)[:1000])

    def _touch_heartbeat(self) -> None:
        try:
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.warning("Failed to update heartbeat file: %s", HEARTBEAT_FILE)

    def _cleanup_heartbeat(self) -> None:
        if HEARTBEAT_FILE.exists():
            with contextlib.suppress(OSError):
                HEARTBEAT_FILE.unlink()


# ---------------------------------------------------------------------------
# Task handlers
# ---------------------------------------------------------------------------


def _handle_spin_up_ranges(task: CTFScheduledTask, shutdown_check=None) -> None:
    from ctf.services.range import provision_event_ranges_throttled

    event = task.event
    spinup_window = event.range_spinup_minutes * 60  # convert to seconds
    result = provision_event_ranges_throttled(
        event_id=event.pk,
        spinup_window_seconds=spinup_window,
        shutdown_check=shutdown_check,
    )
    logger.info(
        "SPIN_UP_RANGES result for event %s: %s",
        event.pk,
        result,
    )


def _handle_cleanup_ranges(task: CTFScheduledTask, shutdown_check=None) -> None:
    from ctf.services.range import cleanup_event_ranges

    result = cleanup_event_ranges(task.event_id)
    logger.info("CLEANUP_RANGES result for event %s: %s", task.event_id, result)


def _handle_event_start(task: CTFScheduledTask, shutdown_check=None) -> None:
    from ctf.services.event import activate_event

    activate_event(task.event)


def _handle_event_end(task: CTFScheduledTask, shutdown_check=None) -> None:
    from ctf.services.event import complete_event

    complete_event(task.event)

    # Also trigger cleanup if auto_cleanup is enabled
    if task.event.auto_cleanup:
        from ctf.services.range import cleanup_event_ranges

        result = cleanup_event_ranges(task.event_id)
        logger.info("EVENT_END cleanup for event %s: %s", task.event_id, result)


def _handle_send_reminder(task: CTFScheduledTask, shutdown_check=None) -> None:
    logger.warning(
        "SEND_REMINDER not yet implemented for event %s",
        task.event_id,
    )


def _handle_release_challenge(task: CTFScheduledTask, shutdown_check=None) -> None:
    from ctf.services.challenge import release_challenge

    challenge_id = task.metadata.get("challenge_id")
    if not challenge_id:
        raise ValueError("RELEASE_CHALLENGE task missing challenge_id in metadata")

    result = release_challenge(challenge_id)
    logger.info(
        "RELEASE_CHALLENGE for event %s: challenge %s (%s)",
        task.event_id,
        challenge_id,
        result.name,
    )


TASK_HANDLERS: dict[str, Any] = {
    ScheduledTaskType.SPIN_UP_RANGES.value: _handle_spin_up_ranges,
    ScheduledTaskType.CLEANUP_RANGES.value: _handle_cleanup_ranges,
    ScheduledTaskType.EVENT_START.value: _handle_event_start,
    ScheduledTaskType.EVENT_END.value: _handle_event_end,
    ScheduledTaskType.SEND_REMINDER.value: _handle_send_reminder,
    ScheduledTaskType.RELEASE_CHALLENGE.value: _handle_release_challenge,
}
