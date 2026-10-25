"""CTFScheduledTask — the one-shot scheduled-automation row for CTF events.

Extracted from ``ctf/models/notification.py`` (#2099) to keep each model file
under the python:S104 file-size budget after the claim-fencing methods were added.
The model stays in the ``ctf`` app with its existing ``ctf_scheduled_task`` table,
and ``ctf/models/__init__.py`` re-exports it, so ``from ctf.models import
CTFScheduledTask`` keeps working unchanged and no migration is needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db import connection, models, transaction
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


class CTFScheduledTask(CTFBaseModel):
    """Scheduled automation task for CTF events.

    Tracks tasks like range provisioning and cleanup.

    Note: Tasks are database records only -- no background worker (e.g. Celery)
    auto-executes them yet. A management command or cron job is needed to poll
    for due tasks and run them.

    Attributes:
        event: The event this task belongs to.
        task_type: Type of scheduled task.
        scheduled_for: When the task should execute.
        executed_at: When the task was executed.
        status: Current task status.
        error_message: Error details if failed.
        metadata: Additional task-specific data.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="scheduled_tasks",
        help_text="Event this task belongs to",
    )
    task_type = models.CharField(
        max_length=30,
        choices=ScheduledTaskType.choices(),
        help_text="Type of scheduled task",
    )
    scheduled_for = models.DateTimeField(
        db_index=True,
        help_text="When the task should execute",
    )
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the task was executed",
    )
    status = models.CharField(
        max_length=20,
        choices=ScheduledTaskStatus.choices(),
        default=ScheduledTaskStatus.PENDING.value,
        db_index=True,
        help_text="Current task status",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error details if failed",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional task-specific data",
    )
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Retries already consumed by this task (#526)",
    )
    max_retries = models.PositiveSmallIntegerField(
        default=3,
        help_text="Transient-failure retries allowed before the task is marked failed (#526)",
    )
    claim_token = models.UUIDField(
        null=True,
        blank=True,
        help_text="Current worker claim owner; completion/requeue are fenced on this token (#2099)",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_scheduled_task"
        ordering = ["scheduled_for"]
        verbose_name = "CTF Scheduled Task"
        verbose_name_plural = "CTF Scheduled Tasks"
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["event", "task_type"]),
        ]

    def __str__(self) -> str:
        """Return task description."""
        return f"[{self.task_type}] {self.event.name} @ {self.scheduled_for}"

    @property
    def is_due(self) -> bool:
        """Return True if task is ready to execute."""
        return self.status == ScheduledTaskStatus.PENDING.value and timezone.now() >= self.scheduled_for

    def mark_running(self, claim_token: UUID | None = None) -> None:
        """Mark task as running and record the claiming worker's fence token (#2099).

        The scheduler passes a unique ``claim_token`` at claim time so its later
        terminal transition can be fenced against a cancellation or a stale-lease
        reclaim that happened while the handler ran.
        """
        self.status = ScheduledTaskStatus.RUNNING.value
        self.claim_token = claim_token
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('shifter.communication_writer', 'ledger_v1', true)")
            self.save(update_fields=["status", "claim_token", "updated_at"])
        logger.info("Task %s started: %s", self.task_type, self.pk)

    def complete_if_claimed(self, claim_token: UUID) -> bool:
        """Complete this task only if it is still RUNNING under ``claim_token``.

        A conditional UPDATE, so a worker whose lease was reclaimed, or whose task
        was cancelled/superseded while its handler ran, cannot overwrite the newer
        state as COMPLETED (#2099). Returns True when this worker won the transition.
        """
        won = CTFScheduledTask.objects.filter(
            pk=self.pk, status=ScheduledTaskStatus.RUNNING.value, claim_token=claim_token
        ).update(status=ScheduledTaskStatus.COMPLETED.value, executed_at=timezone.now(), updated_at=timezone.now())
        if won:
            logger.info("Task %s completed: %s", self.task_type, self.pk)
        else:
            logger.info("Task %s completion fenced (cancelled/superseded/reclaimed): %s", self.task_type, self.pk)
        return bool(won)

    def requeue_if_claimed(self, claim_token: UUID) -> bool:
        """Requeue an interrupted task to PENDING only if still claimed by ``claim_token``.

        Used when a handler is cut short by shutdown: the work is recoverable
        (idempotent), so the task is made due again and its claim token cleared so
        the next poll re-claims it cleanly. Fenced like completion (#2099).
        """
        won = CTFScheduledTask.objects.filter(
            pk=self.pk, status=ScheduledTaskStatus.RUNNING.value, claim_token=claim_token
        ).update(
            status=ScheduledTaskStatus.PENDING.value,
            scheduled_for=timezone.now(),
            claim_token=None,
            updated_at=timezone.now(),
        )
        if won:
            logger.info("Task %s requeued for resume: %s", self.task_type, self.pk)
        return bool(won)

    def cancel_if_active(self) -> bool:
        """Cancel this task only if it is still PENDING or RUNNING.

        A conditional transition so a late cancellation can never recall a task
        that already reached a terminal state (COMPLETED/FAILED). Completion and
        cancellation are therefore mutually exclusive (#2099). Returns True when
        this call performed the cancellation.
        """
        won = CTFScheduledTask.objects.filter(
            pk=self.pk,
            status__in=(ScheduledTaskStatus.PENDING.value, ScheduledTaskStatus.RUNNING.value),
        ).update(status=ScheduledTaskStatus.CANCELLED.value, updated_at=timezone.now())
        if won:
            logger.info("Task %s cancelled: %s", self.task_type, self.pk)
        return bool(won)

    def reschedule_to_if_claimed(self, claim_token: UUID, when: datetime) -> bool:
        """Reschedule this task to ``when`` (PENDING) only if still claimed by ``claim_token``.

        Used when a handler determines the occurrence is not yet due (early tick /
        backward clock jump): the task is made due again at the authored time and its
        claim token cleared, rather than completed or spun. Fenced like completion.
        """
        won = CTFScheduledTask.objects.filter(
            pk=self.pk, status=ScheduledTaskStatus.RUNNING.value, claim_token=claim_token
        ).update(
            status=ScheduledTaskStatus.PENDING.value,
            scheduled_for=when,
            claim_token=None,
            updated_at=timezone.now(),
        )
        return bool(won)

    def retry_or_fail_if_claimed(self, error: str, claim_token: UUID) -> bool:
        """Apply the retry/backoff-or-fail transition only if still claimed (fence).

        A crashing handler must not resurrect a task that was cancelled or reclaimed
        while it ran. Re-reads the row under lock and applies :meth:`retry_or_fail`
        only when this worker still owns the RUNNING claim. Returns whether it
        applied.
        """
        with transaction.atomic():
            locked = (
                CTFScheduledTask.objects.select_for_update()
                .filter(pk=self.pk, status=ScheduledTaskStatus.RUNNING.value, claim_token=claim_token)
                .first()
            )
            if locked is None:
                logger.info("Task %s failure fenced (cancelled/superseded/reclaimed): %s", self.task_type, self.pk)
                return False
            locked.retry_or_fail(error)
            return True

    def recover_stale_if_running(self, cutoff: datetime, error: str) -> str | None:
        """Recover a stale RUNNING task by requeuing it within its retry budget.

        A worker that died leaves its task RUNNING and never completed, so the work
        is requeued (bounded by the same retry budget so a task that always crashes
        its worker cannot recover forever, #2099). Heartbeat-aware and node-safe:
        re-reads under lock and re-checks the still-stale RUNNING condition, so two
        schedulers cannot both recover one row and a task that heartbeated between
        the read and the write is left alone. Returns ``"requeued"``, ``"failed"``,
        or ``None`` when it was no longer eligible.
        """
        with transaction.atomic():
            locked = (
                CTFScheduledTask.objects.select_for_update(skip_locked=True)
                .filter(pk=self.pk, status=ScheduledTaskStatus.RUNNING.value, updated_at__lt=cutoff)
                .first()
            )
            if locked is None:
                return None
            requeued = locked.retry_or_fail(error)
            return "requeued" if requeued else "failed"

    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = ScheduledTaskStatus.COMPLETED.value
        self.executed_at = timezone.now()
        self.save(update_fields=["status", "executed_at", "updated_at"])
        logger.info("Task %s completed: %s", self.task_type, self.pk)

    def mark_failed(self, error: str) -> None:
        """Mark task as failed.

        Args:
            error: Error message to record.
        """
        self.status = ScheduledTaskStatus.FAILED.value
        self.executed_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "executed_at", "error_message", "updated_at"])
        logger.error("Task %s failed: %s - %s", self.task_type, self.pk, error)

    def retry_or_fail(self, error: str) -> bool:
        """Requeue after a failure with exponential backoff, or mark failed (#526).

        Handlers are idempotent (destroy skips destroyed ranges, transitions
        guard on state, notification sends are per-recipient best-effort), so a
        transient failure — mail outage, provider throttle, deadlock — is
        retried up to ``max_retries`` times at 5 · 2^n minute intervals before
        the task is recorded as failed.

        Returns:
            True when the task was requeued, False when it was marked failed.
        """
        if self.retry_count >= self.max_retries:
            self.mark_failed(error)
            return False
        self.retry_count += 1
        delay_minutes = 5 * (2 ** (self.retry_count - 1))
        self.status = ScheduledTaskStatus.PENDING.value
        self.scheduled_for = timezone.now() + timedelta(minutes=delay_minutes)
        self.error_message = error
        self.claim_token = None
        self.save(
            update_fields=["status", "scheduled_for", "retry_count", "error_message", "claim_token", "updated_at"]
        )
        logger.warning(
            "Task %s failed (attempt %d/%d), retrying in %d min: %s - %s",
            self.task_type,
            self.retry_count,
            self.max_retries,
            delay_minutes,
            self.pk,
            error,
        )
        return True

    def requeue_for_resume(self) -> None:
        """Return an interrupted task to PENDING so the scheduler resumes it.

        Used when a long-running handler is cut short by shutdown: the work is
        recoverable (idempotent on the remaining items), so the task is made due
        again rather than recorded as completed.
        """
        self.status = ScheduledTaskStatus.PENDING.value
        self.scheduled_for = timezone.now()
        self.claim_token = None
        self.save(update_fields=["status", "scheduled_for", "claim_token", "updated_at"])
        logger.info("Task %s requeued for resume: %s", self.task_type, self.pk)
