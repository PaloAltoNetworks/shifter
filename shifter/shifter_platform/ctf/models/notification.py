"""CTFNotification, CTFEmailTemplate, CTFScheduledTask — admin and automation.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone

from ctf.enums import (
    NotificationStatus,
    NotificationType,
    ScheduledTaskStatus,
    ScheduledTaskType,
)

from ._base import CTFBaseModel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CTFNotification(CTFBaseModel):
    """Notification record for CTF events.

    Tracks scheduled and sent notifications.

    Attributes:
        event: The event this notification belongs to.
        notification_type: Type of notification.
        subject: Email subject line.
        body: Email body content.
        status: Current notification status.
        recipient_filter: Who should receive (all, organizers, participants).
        recipient_emails: Specific emails for individual targeting.
        scheduled_at: When to send (null = immediate).
        sent_at: When actually sent.
        sent_count: Number of emails sent.
        error_message: Error details if failed.
        created_by: User who created notification.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="Event this notification belongs to",
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices(),
        help_text="Type of notification",
    )
    subject = models.CharField(
        max_length=200,
        help_text="Email subject line",
    )
    body = models.TextField(
        help_text="Email body content (supports Markdown)",
    )
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices(),
        default=NotificationStatus.DRAFT.value,
        db_index=True,
        help_text="Current notification status",
    )
    recipient_filter = models.CharField(
        max_length=20,
        choices=[
            ("all", "All Participants"),
            ("organizers", "Organizers Only"),
            ("participants", "Participants Only"),
            ("individual", "Individual Recipients"),
        ],
        default="participants",
        help_text="Who should receive this notification",
    )
    recipient_emails = models.JSONField(
        default=list,
        blank=True,
        help_text="Specific emails for individual targeting",
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When to send (null = immediate)",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When actually sent",
    )
    sent_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of emails sent",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error details if failed",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_notifications_created",
        help_text="User who created notification",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_notification"
        ordering = ["-created_at"]
        verbose_name = "CTF Notification"
        verbose_name_plural = "CTF Notifications"
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        """Return notification description."""
        return f"[{self.notification_type}] {self.subject}"


class CTFEmailTemplate(CTFBaseModel):
    """Per-event email template override.

    Organizers can customise email templates for specific notification types
    within their event.  When a custom template exists it is rendered instead
    of the default filesystem template.

    Attributes:
        event: The event this template belongs to.
        notification_type: Which notification type this template overrides.
        subject: Custom subject line (optional — falls back to default).
        html_body: Custom HTML body using Django template syntax.
        text_body: Custom plain-text body using Django template syntax.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="email_templates",
        help_text="Event this template belongs to",
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices(),
        help_text="Notification type this template overrides",
    )
    subject = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Custom subject line (leave blank to use default)",
    )
    html_body = models.TextField(
        help_text="Custom HTML email body (Django template syntax)",
    )
    text_body = models.TextField(
        help_text="Custom plain-text email body (Django template syntax)",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_email_template"
        ordering = ["notification_type"]
        verbose_name = "CTF Email Template"
        verbose_name_plural = "CTF Email Templates"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "notification_type"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_email_template_per_event_type",
            ),
        ]

    def __str__(self) -> str:
        """Return template description."""
        return f"{self.event.name} - {self.notification_type}"


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

    def mark_running(self) -> None:
        """Mark task as running."""
        self.status = ScheduledTaskStatus.RUNNING.value
        self.save(update_fields=["status", "updated_at"])
        logger.info("Task %s started: %s", self.task_type, self.pk)

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

    def mark_cancelled(self) -> None:
        """Mark task as cancelled."""
        self.status = ScheduledTaskStatus.CANCELLED.value
        self.save(update_fields=["status", "updated_at"])
        logger.info("Task %s cancelled: %s", self.task_type, self.pk)
