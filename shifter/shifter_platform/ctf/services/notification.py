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
    """Send magic link emails to all participants.

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

    participants = CTFParticipant.objects.filter(event=event)

    sent = 0
    failed = 0

    for participant in participants:
        try:
            registration_url = _build_registration_url(participant.invite_token)
            html_content, text_content, custom_subject = _render_email(
                "invitation",
                {
                    "event": event,
                    "participant": participant,
                    "invite_token": participant.invite_token,
                    "registration_url": registration_url,
                },
                event=event,
            )
            success = _send_email(
                recipient=participant.email,
                subject=custom_subject or f"You're invited to {event.name}",
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
            # Link to the CTF range page where participants can access their range
            # via the platform's standard Guacamole RDP flow.
            from django.conf import settings
            from django.urls import reverse

            range_page_url = reverse("ctf:ctf_range")
            base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
            access_url = f"{base}{range_page_url}"

            html_content, text_content, custom_subject = _render_email(
                "credentials",
                {
                    "event": event,
                    "participant": participant,
                    "access_url": access_url,
                },
                event=event,
            )
            success = _send_email(
                recipient=participant.email,
                subject=custom_subject or f"Your credentials for {event.name}",
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
            html_content, text_content, custom_subject = _render_email(
                "reminder",
                {
                    "event": event,
                    "participant": participant,
                    "hours_before": hours_before,
                },
                event=event,
            )
            success = _send_email(
                recipient=participant.email,
                subject=custom_subject or f"Reminder: {event.name} starts soon",
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
            html_content, text_content, custom_subject = _render_email(
                "announcement",
                {
                    "event": event,
                    "participant": participant,
                    "subject": subject,
                    "body": body,
                },
                event=event,
            )
            success = _send_email(
                recipient=participant.email,
                subject=custom_subject or subject,
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


def notify_organizer_provision_failure(
    event_id: UUID,
    failures: list[dict[str, str]],
) -> None:
    """Notify the event organizer of provisioning failures.

    Args:
        event_id: UUID of the event.
        failures: List of dicts with participant_id and error.
    """
    if not failures:
        return

    logger.info("Notifying organizer of %d provisioning failures for event %s", len(failures), event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        logger.error("Cannot notify: event %s not found", event_id)
        return

    organizer = event.created_by
    if not organizer or not organizer.email:
        logger.warning("Cannot notify: event %s has no organizer email", event_id)
        return

    html_content, text_content, custom_subject = _render_email(
        "provision_failure",
        {
            "event": event,
            "failures": failures,
            "failure_count": len(failures),
        },
        event=event,
    )

    success = _send_email(
        recipient=organizer.email,
        subject=custom_subject or f"Range provisioning failures: {event.name}",
        html_content=html_content,
        text_content=text_content,
    )

    if success:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.PROVISION_FAILURE.value,
            subject=f"Provisioning failures for {event.name}",
            body=f"{len(failures)} participant(s) failed provisioning",
            status=NotificationStatus.SENT.value,
            recipient_filter="organizers",
            sent_count=1,
            created_by=organizer,
        )


def notify_organizer_event_start(event_id: UUID) -> None:
    """Notify the event organizer that the event has automatically started.

    Args:
        event_id: UUID of the event.
    """
    logger.info("Notifying organizer of event start for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        logger.error("Cannot notify: event %s not found", event_id)
        return

    organizer = event.created_by
    if not organizer or not organizer.email:
        logger.warning("Cannot notify: event %s has no organizer email", event_id)
        return

    html_content, text_content, custom_subject = _render_email(
        "event_start",
        {"event": event},
        event=event,
    )

    success = _send_email(
        recipient=organizer.email,
        subject=custom_subject or f"Event started: {event.name}",
        html_content=html_content,
        text_content=text_content,
    )

    if success:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.EVENT_START.value,
            subject=f"Event started: {event.name}",
            body=f"Event {event.name} has automatically started",
            status=NotificationStatus.SENT.value,
            recipient_filter="organizers",
            sent_count=1,
            created_by=organizer,
        )


def notify_organizer_event_end(event_id: UUID) -> None:
    """Notify the event organizer that the event has automatically ended.

    Args:
        event_id: UUID of the event.
    """
    logger.info("Notifying organizer of event end for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        logger.error("Cannot notify: event %s not found", event_id)
        return

    organizer = event.created_by
    if not organizer or not organizer.email:
        logger.warning("Cannot notify: event %s has no organizer email", event_id)
        return

    html_content, text_content, custom_subject = _render_email(
        "event_end",
        {"event": event},
        event=event,
    )

    success = _send_email(
        recipient=organizer.email,
        subject=custom_subject or f"Event ended: {event.name}",
        html_content=html_content,
        text_content=text_content,
    )

    if success:
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.EVENT_END.value,
            subject=f"Event ended: {event.name}",
            body=f"Event {event.name} has automatically ended",
            status=NotificationStatus.SENT.value,
            recipient_filter="organizers",
            sent_count=1,
            created_by=organizer,
        )


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
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}{path}"


def _send_email(
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
) -> bool:
    """Send an email using the shared platform email service.

    Delegates to ``shared.email.send_email`` which handles error logging
    and never raises.  Uses ``CTF_FROM_EMAIL`` as the sender address.

    Args:
        recipient: Email address.
        subject: Email subject.
        html_content: HTML email body.
        text_content: Plain text email body.

    Returns:
        True if sent successfully.
    """
    from django.conf import settings

    from shared.email import send_email

    return send_email(recipient, subject, html_content, text_content, from_email=settings.CTF_FROM_EMAIL)


def _render_email(
    template_name: str,
    context: dict,
    event: CTFEvent | None = None,
) -> tuple[str, str, str]:
    """Render email templates.

    If *event* is provided and has a custom template for the given
    notification type, the custom template is rendered from the database.
    Otherwise the default filesystem template is used.

    Args:
        template_name: Base name / notification type (e.g., "invitation").
        context: Template context.
        event: Optional event for custom template lookup.

    Returns:
        Tuple of (html_content, text_content, custom_subject).
        custom_subject is non-empty only when a custom template with a
        subject override is used; callers should prefer it over their
        default subject when non-empty.
    """
    # Map filesystem template names to NotificationType enum values where
    # they differ (the "invitation" template corresponds to the "invite" type).
    _TEMPLATE_TO_TYPE = {"invitation": "invite"}

    if event is not None:
        from ctf.models import CTFEmailTemplate

        lookup_type = _TEMPLATE_TO_TYPE.get(template_name, template_name)
        custom = CTFEmailTemplate.objects.filter(
            event=event,
            notification_type=lookup_type,
        ).first()
        if custom is not None:
            from django.template import Context, Template

            # Safe: Django's template engine does not allow arbitrary code
            # execution.  Only authenticated event organizers can write templates.
            html_content = Template(custom.html_body).render(Context(context))
            text_content = Template(custom.text_body).render(Context(context))
            return html_content, text_content, custom.subject or ""

    from shared.email import render_template

    html, text = render_template(f"ctf/email/{template_name}", context)
    return html, text, ""
