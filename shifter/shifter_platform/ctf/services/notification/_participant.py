"""CTF participant-facing notifications: invitations, credentials, reminders,
announcements, and notification scheduling.

``CTFEvent`` / ``CTFParticipant`` / ``CTFNotification`` and the email helpers
(``_send_email``, ``_render_email``) are resolved through the
``ctf.services.notification`` package at call time
(``from ctf.services import notification as _n``) rather than imported
directly, so ``unittest.mock.patch`` targets of the form
``patch("ctf.services.notification.<name>")`` keep working after the
package split -- see the package ``__init__`` docstring for the full
rationale.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ctf.enums import NotificationStatus, NotificationType, ScheduledTaskType
from ctf.exceptions import CTFNotFoundError
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from datetime import datetime

    from django.contrib.auth.models import User

    from ctf.models import CTFNotification

logger = logging.getLogger(__name__)


def send_login_info(event_id: UUID) -> dict[str, Any]:
    """Queue non-secret login information for participants with delivery email.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with sent count and any errors.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Sending invitations for event %s", safe_log_value(event_id))

    from ctf.services import notification as _n

    try:
        event = _n.CTFEvent.objects.get(pk=event_id)
    except _n.CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = _n.CTFParticipant.objects.filter(event=event)

    queued = 0
    failed = 0

    for participant in participants:
        if not participant.email:
            continue
        try:
            from ctf.services.participant.credentials import reset_participant_credentials

            reset_participant_credentials(participant.pk)

            from django.utils import timezone

            participant.login_info_sent_at = timezone.now()
            participant.save(update_fields=["login_info_sent_at", "updated_at"])
            queued += 1
        except Exception:
            logger.exception("Failed to send invitation to %s", safe_log_value(participant.email))
            failed += 1

    # Create notification record
    if queued > 0:
        _n.CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.INVITE.value,
            subject=f"Invitations for {event.name}",
            body=f"Queued {queued} invitations",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=queued,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "total": queued + failed,
        "sent": queued,
        "failed": failed,
    }


def send_credentials(event_id: UUID) -> dict[str, Any]:
    """Send credential emails to participants with ready ranges.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with sent count and any errors.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Sending credentials for event %s", safe_log_value(event_id))

    from ctf.services import notification as _n

    try:
        event = _n.CTFEvent.objects.get(pk=event_id)
    except _n.CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = _n.CTFParticipant.objects.filter(
        event=event,
        range_status="ready",
    )

    queued = 0
    failed = 0

    for participant in participants:
        try:
            # Link to the CTF range page where participants can access their range
            # via the platform's standard Guacamole RDP flow.
            from django.conf import settings
            from django.urls import reverse

            range_page_url = reverse("ctf:participant_range")
            base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
            access_url = f"{base}{range_page_url}"

            html_content, text_content, custom_subject = _n._render_email(
                "credentials",
                {
                    "event": event,
                    "participant": participant,
                    "access_url": access_url,
                },
                event=event,
            )
            _n._send_email(
                recipient=participant.email,
                subject=custom_subject or f"Your credentials for {event.name}",
                html_content=html_content,
                text_content=text_content,
            )
            queued += 1
        except Exception:
            logger.exception("Failed to send credentials to %s", safe_log_value(participant.email))
            failed += 1

    if queued > 0:
        _n.CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.CREDENTIALS.value,
            subject=f"Credentials for {event.name}",
            body=f"Queued credentials for {queued} participants",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=queued,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "total": queued + failed,
        "sent": queued,
        "failed": failed,
    }


def send_reminder(event_id: UUID, hours_before: int = 24) -> dict[str, Any]:
    """Send reminder emails to registered participants.

    Args:
        event_id: UUID of the event.
        hours_before: Hours before event this reminder is for.

    Returns:
        Dict with sent count and any errors.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Sending %d-hour reminder for event %s", hours_before, safe_log_value(event_id))

    from ctf.services import notification as _n

    try:
        event = _n.CTFEvent.objects.get(pk=event_id)
    except _n.CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = _n.CTFParticipant.objects.filter(
        event=event,
        registered_at__isnull=False,
    )

    queued = 0
    failed = 0

    # Build access URL and timezone-aware start time for template context
    from zoneinfo import ZoneInfo

    from django.conf import settings
    from django.urls import reverse

    event_page_url = reverse("ctf:participant_event")
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    access_url = f"{base}{event_page_url}"

    tz_name = event.event_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    event_start_local = event.event_start.astimezone(tz)

    for participant in participants:
        try:
            html_content, text_content, custom_subject = _n._render_email(
                "reminder",
                {
                    "event": event,
                    "participant": participant,
                    "hours_before": hours_before,
                    "access_url": access_url,
                    "event_start_local": event_start_local,
                    "event_timezone": tz_name,
                },
                event=event,
            )
            _n._send_email(
                recipient=participant.email,
                subject=custom_subject or f"Reminder: {event.name} starts soon",
                html_content=html_content,
                text_content=text_content,
            )
            queued += 1
        except Exception:
            logger.exception("Failed to send reminder to %s", safe_log_value(participant.email))
            failed += 1

    if queued > 0:
        _n.CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.REMINDER.value,
            subject=f"Reminder for {event.name}",
            body=f"Queued {queued} reminders",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=queued,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "hours_before": hours_before,
        "total": queued + failed,
        "sent": queued,
        "failed": failed,
    }


def send_announcement(
    event_id: UUID,
    subject: str,
    body: str,
    created_by: User,
) -> CTFNotification:
    """Send an announcement to all participants.

    Args:
        event_id: UUID of the event.
        subject: Email subject.
        body: Email body content.
        created_by: User creating the announcement.

    Returns:
        The CTFNotification record.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    # Do not log the user-controlled announcement subject (SonarCloud S5145 /
    # log-injection): the event id is sufficient to trace the operation.
    logger.info("Sending announcement for event %s", safe_log_value(event_id))

    from ctf.services import notification as _n

    try:
        event = _n.CTFEvent.objects.get(pk=event_id)
    except _n.CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    notification = _n.CTFNotification.objects.create(
        event=event,
        notification_type=NotificationType.ANNOUNCEMENT.value,
        subject=subject,
        body=body,
        status=NotificationStatus.SENDING.value,
        recipient_filter="participants",
        created_by=created_by,
    )

    participants = _n.CTFParticipant.objects.filter(event=event)
    queued = 0

    for participant in participants:
        try:
            html_content, text_content, custom_subject = _n._render_email(
                "announcement",
                {
                    "event": event,
                    "participant": participant,
                    "subject": subject,
                    "body": body,
                },
                event=event,
            )
            _n._send_email(
                recipient=participant.email,
                subject=custom_subject or subject,
                html_content=html_content,
                text_content=text_content,
            )
            queued += 1
        except Exception:
            logger.exception("Failed to send announcement to %s", safe_log_value(participant.email))

    from django.utils import timezone

    notification.sent_count = queued
    notification.sent_at = timezone.now()
    notification.status = NotificationStatus.SENT.value
    notification.save(update_fields=["sent_count", "sent_at", "status", "updated_at"])

    return notification


def schedule_notification(
    notification_id: UUID,
    scheduled_at: datetime,
) -> CTFNotification:
    """Schedule a notification for future sending.

    Args:
        notification_id: UUID of the notification.
        scheduled_at: When to send the notification.

    Returns:
        The updated CTFNotification record.

    Raises:
        CTFNotFoundError: If notification doesn't exist.
    """
    from ctf.services import notification as _n

    try:
        notification = _n.CTFNotification.objects.get(pk=notification_id)
    except _n.CTFNotification.DoesNotExist:
        raise CTFNotFoundError(
            f"Notification {notification_id} not found",
            details={"notification_id": str(notification_id)},
        ) from None

    notification.scheduled_at = scheduled_at
    notification.status = NotificationStatus.SCHEDULED.value
    notification.save(update_fields=["scheduled_at", "status", "updated_at"])

    # Create scheduled task
    from ctf.models import CTFScheduledTask

    CTFScheduledTask.objects.create(
        event=notification.event,
        task_type=ScheduledTaskType.SEND_REMINDER.value,
        scheduled_for=scheduled_at,
        metadata={"notification_id": str(notification_id)},
    )

    return notification
