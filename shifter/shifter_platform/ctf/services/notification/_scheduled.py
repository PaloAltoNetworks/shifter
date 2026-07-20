"""Announcement + scheduled-notification delivery and real-time mirroring.

Split from the former ``notification`` module (CTF-802/803/804, #667) and
re-exported through ``ctf.services.notification``. Email helpers
(``_send_email`` / ``_render_email``) resolve through the package at call
time (``from ctf.services import notification as _n``) so tests that patch
``ctf.services.notification._send_email`` are honoured (see the package
PATCH LOCALITY note).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from ctf.enums import NotificationStatus, NotificationType, ScheduledTaskType
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFNotification, CTFParticipant
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


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
    logger.info("Sending announcement for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    notification = CTFNotification.objects.create(
        event=event,
        notification_type=NotificationType.ANNOUNCEMENT.value,
        subject=subject,
        body=body,
        status=NotificationStatus.SENDING.value,
        recipient_filter="participants",
        created_by=created_by,
    )
    _deliver_announcement(notification)
    return notification


def _deliver_announcement(notification: CTFNotification) -> int:
    """Email an announcement row to every participant and mark it sent.

    Shared by the immediate path (:func:`send_announcement`) and the
    scheduler's SEND_NOTIFICATION handler, so scheduled announcements
    deliver the drafted content (#667). Also mirrors the announcement onto
    the real-time bus (CTF-802/CTF-803).
    """
    from django.utils import timezone

    from ctf.services import notification as _n
    from ctf.services.notification.realtime import publish_event_notification

    event = notification.event
    subject = notification.subject
    body = notification.body
    participants = CTFParticipant.objects.filter(event=event).exclude(email="")
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

    notification.sent_count = queued
    notification.sent_at = timezone.now()
    notification.status = NotificationStatus.SENT.value
    notification.save(update_fields=["sent_count", "sent_at", "status", "updated_at"])

    publish_event_notification(
        event,
        "announcement",
        {"subject": subject, "body": body, "notification_id": str(notification.pk)},
    )
    return queued


def cancel_scheduled_notification(notification_id: UUID) -> CTFNotification:
    """Cancel a scheduled notification before delivery (CTF-804).

    Reverts the row to draft and cancels its pending scheduler task.
    """
    from ctf.enums import ScheduledTaskStatus
    from ctf.exceptions import CTFStateError
    from ctf.models import CTFScheduledTask

    try:
        notification = CTFNotification.objects.get(pk=notification_id)
    except CTFNotification.DoesNotExist:
        raise CTFNotFoundError(
            f"Notification {notification_id} not found",
            details={"notification_id": str(notification_id)},
        ) from None
    if notification.status != NotificationStatus.SCHEDULED.value:
        raise CTFStateError(
            "Only scheduled notifications can be cancelled",
            details={"notification_id": str(notification_id), "status": notification.status},
        )
    notification.status = NotificationStatus.DRAFT.value
    notification.scheduled_at = None
    notification.save(update_fields=["status", "scheduled_at", "updated_at"])
    for task in CTFScheduledTask.objects.filter(
        event=notification.event,
        task_type=ScheduledTaskType.SEND_NOTIFICATION.value,
        status=ScheduledTaskStatus.PENDING.value,
        metadata__notification_id=str(notification_id),
    ):
        task.mark_cancelled()
    logger.info("Cancelled scheduled notification %s", safe_log_value(notification_id))
    return notification


def deliver_scheduled_notification(notification_id: UUID) -> int:
    """Deliver a scheduled notification's drafted content (#667 scheduler path)."""
    from ctf.exceptions import CTFStateError

    try:
        notification = CTFNotification.objects.select_related("event").get(pk=notification_id)
    except CTFNotification.DoesNotExist:
        raise CTFNotFoundError(
            f"Notification {notification_id} not found",
            details={"notification_id": str(notification_id)},
        ) from None
    if notification.status != NotificationStatus.SCHEDULED.value:
        raise CTFStateError(
            "Notification is not scheduled",
            details={"notification_id": str(notification_id), "status": notification.status},
        )
    notification.status = NotificationStatus.SENDING.value
    notification.save(update_fields=["status", "updated_at"])
    return _deliver_announcement(notification)


def schedule_notification(
    notification_id: UUID,
    scheduled_at: datetime,
) -> CTFNotification:
    """Schedule a notification for future sending.

    Creates a ``SEND_NOTIFICATION`` scheduler task carrying the notification
    id so the scheduler delivers the drafted announcement (#667), not a
    reminder.

    Raises:
        CTFNotFoundError: If notification doesn't exist.
    """
    try:
        notification = CTFNotification.objects.get(pk=notification_id)
    except CTFNotification.DoesNotExist:
        raise CTFNotFoundError(
            f"Notification {notification_id} not found",
            details={"notification_id": str(notification_id)},
        ) from None

    notification.scheduled_at = scheduled_at
    notification.status = NotificationStatus.SCHEDULED.value
    notification.save(update_fields=["scheduled_at", "status", "updated_at"])

    from ctf.models import CTFScheduledTask

    CTFScheduledTask.objects.create(
        event=notification.event,
        task_type=ScheduledTaskType.SEND_NOTIFICATION.value,
        scheduled_for=scheduled_at,
        metadata={"notification_id": str(notification_id)},
    )

    return notification
