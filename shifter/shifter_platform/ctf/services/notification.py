"""CTF Notification service.

Provides business logic for email notifications.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ctf.enums import NotificationStatus, NotificationType, ScheduledTaskType
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFNotification, CTFParticipant

if TYPE_CHECKING:
    from datetime import datetime

    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def send_invitations(event_id: UUID) -> dict[str, Any]:
    """Send invitation emails to all uninvited participants.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with sent count and any errors.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Sending invitations for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event=event,
        invited_at__isnull=True,
    )

    sent = 0
    failed = 0

    for participant in participants:
        try:
            registration_url = _build_registration_url(participant.invite_token)
            html_content, text_content = _render_email(
                "invitation",
                {
                    "event": event,
                    "participant": participant,
                    "invite_token": participant.invite_token,
                    "registration_url": registration_url,
                },
            )
            success = _send_email(
                recipient=participant.email,
                subject=f"You're invited to {event.name}",
                html_content=html_content,
                text_content=text_content,
            )
            if success:
                from django.utils import timezone

                participant.invited_at = timezone.now()
                participant.save(update_fields=["invited_at", "updated_at"])
                sent += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed to send invitation to %s", participant.email)
            failed += 1

    # Create notification record
    if sent > 0:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.INVITE.value,
            subject=f"Invitations for {event.name}",
            body=f"Sent {sent} invitations",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=sent,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "total": sent + failed,
        "sent": sent,
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
    logger.info("Sending credentials for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event=event,
        range_status="ready",
    )

    sent = 0
    failed = 0

    for participant in participants:
        try:
            # Get access URL for the participant
            from ctf.services import range as range_service

            try:
                access_url = range_service.get_range_access_url(participant.pk)
            except Exception:
                access_url = None

            html_content, text_content = _render_email(
                "credentials",
                {
                    "event": event,
                    "participant": participant,
                    "access_url": access_url,
                },
            )
            success = _send_email(
                recipient=participant.email,
                subject=f"Your credentials for {event.name}",
                html_content=html_content,
                text_content=text_content,
            )
            if success:
                sent += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed to send credentials to %s", participant.email)
            failed += 1

    if sent > 0:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.CREDENTIALS.value,
            subject=f"Credentials for {event.name}",
            body=f"Sent credentials to {sent} participants",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=sent,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "total": sent + failed,
        "sent": sent,
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
    logger.info("Sending %d-hour reminder for event %s", hours_before, event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event=event,
        registered_at__isnull=False,
    )

    sent = 0
    failed = 0

    for participant in participants:
        try:
            html_content, text_content = _render_email(
                "reminder",
                {
                    "event": event,
                    "participant": participant,
                    "hours_before": hours_before,
                },
            )
            success = _send_email(
                recipient=participant.email,
                subject=f"Reminder: {event.name} starts soon",
                html_content=html_content,
                text_content=text_content,
            )
            if success:
                sent += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed to send reminder to %s", participant.email)
            failed += 1

    if sent > 0:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.REMINDER.value,
            subject=f"Reminder for {event.name}",
            body=f"Sent {sent} reminders",
            status=NotificationStatus.SENT.value,
            recipient_filter="participants",
            sent_count=sent,
            created_by=event.created_by,
        )

    return {
        "event_id": str(event_id),
        "hours_before": hours_before,
        "total": sent + failed,
        "sent": sent,
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
    logger.info("Sending announcement for event %s: %s", event_id, subject)

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

    participants = CTFParticipant.objects.filter(event=event)
    sent = 0

    for participant in participants:
        try:
            html_content, text_content = _render_email(
                "announcement",
                {
                    "event": event,
                    "participant": participant,
                    "subject": subject,
                    "body": body,
                },
            )
            success = _send_email(
                recipient=participant.email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )
            if success:
                sent += 1
        except Exception:
            logger.exception("Failed to send announcement to %s", participant.email)

    from django.utils import timezone

    notification.sent_count = sent
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

    # Create scheduled task
    from ctf.models import CTFScheduledTask

    CTFScheduledTask.objects.create(
        event=notification.event,
        task_type=ScheduledTaskType.SEND_REMINDER.value,
        scheduled_for=scheduled_at,
        metadata={"notification_id": str(notification_id)},
    )

    return notification


# -----------------------------------------------------------------------------
# Private helpers
# -----------------------------------------------------------------------------


def _build_registration_url(invite_token: str) -> str:
    """Build a full registration URL from an invite token.

    Uses Django's reverse() to generate the path, then prepends the
    configured site URL to produce an absolute link suitable for emails.
    """
    from django.conf import settings
    from django.urls import reverse

    path = reverse("ctf:ctf_register") + f"?token={invite_token}"
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}{path}"


def _send_email(
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
) -> bool:
    """Send an email using Django's email backend.

    Args:
        recipient: Email address.
        subject: Email subject.
        html_content: HTML email body.
        text_content: Plain text email body.

    Returns:
        True if sent successfully.
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.CTF_FROM_EMAIL,
            to=[recipient],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        return True
    except Exception:
        logger.exception("Failed to send email to %s", recipient)
        return False


def _render_email(template_name: str, context: dict) -> tuple[str, str]:
    """Render email templates.

    Args:
        template_name: Base name (e.g., "invitation").
        context: Template context.

    Returns:
        Tuple of (html_content, text_content).
    """
    from django.template.loader import render_to_string

    html_content = render_to_string(f"ctf/email/{template_name}.html", context)
    text_content = render_to_string(f"ctf/email/{template_name}.txt", context)
    return html_content, text_content
