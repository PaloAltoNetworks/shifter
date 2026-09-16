"""CTFNotification, CTFEmailTemplate, CTFWebhook — admin and automation models.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large); CTFScheduledTask was further extracted to
``ctf/models/scheduled_task.py`` (#2099). Public symbols are re-exported by
ctf/models/__init__.py so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models

from ctf.enums import (
    NotificationStatus,
    NotificationType,
)

from ._base import CTFBaseModel

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

    def clean(self) -> None:
        """Reject unsafe placeholder syntax in custom bodies (issue #1095).

        Defense-in-depth alongside the API validator: enforces the flat
        ``{{ name }}`` placeholder policy for admin and direct model saves
        that call ``full_clean()``.
        """
        super().clean()
        from django.core.exceptions import ValidationError

        from ctf.services.email_template import allowed_placeholders, find_template_violations

        allowed = allowed_placeholders(self.notification_type)
        errors = {}
        for field in ("html_body", "text_body"):
            violations = find_template_violations(getattr(self, field) or "", allowed)
            if violations:
                errors[field] = violations[0]
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        """Return template description."""
        return f"{self.event.name} - {self.notification_type}"


class CTFWebhook(CTFBaseModel):
    """One organizer-registered webhook endpoint for an event (CTF-1203).

    Deliveries POST a JSON payload with the event type, timestamp, and
    entity data; a per-webhook secret produces an HMAC-SHA256 signature
    header so receivers can authenticate payloads.
    """

    event = models.ForeignKey(
        "ctf.CTFEvent",
        on_delete=models.CASCADE,
        related_name="webhooks",
        help_text="Event this webhook is scoped to",
    )
    url = models.URLField(
        max_length=500,
        help_text="HTTPS endpoint that receives POSTed JSON payloads",
    )
    secret = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Optional shared secret for the X-Shifter-Signature HMAC header",
    )
    subscribed_events = models.JSONField(
        default=list,
        blank=True,
        help_text="Webhook event types to deliver (empty list means all)",
    )
    active = models.BooleanField(
        default=True,
        help_text="Inactive webhooks are kept for audit but never called",
    )
    last_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Outcome of the most recent delivery attempt",
    )
    last_delivery_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the most recent delivery attempt finished",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_webhook"
        ordering = ["created_at"]
        verbose_name = "CTF Webhook"
        verbose_name_plural = "CTF Webhooks"

    def __str__(self) -> str:
        """Return the webhook endpoint with its event."""
        return f"{self.url} ({self.event_id})"
