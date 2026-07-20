"""Milestone notification sends, split from delivery (python:S104).

Range-ready, provisioning-failure, cleanup-warning, and final-results
messages (CTF-801/CTF-1003). Behavior unchanged; import through
:mod:`ctf.services.notification` as before.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ctf.enums import NotificationStatus, NotificationType
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFNotification, CTFParticipant
from ctf.services.notification._email import _render_email, _send_email
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def send_cleanup_warning(event_id: UUID) -> dict[str, Any]:
    """Warn registered participants that range destruction is imminent (CTF-1003).

    Delivered through the announcement pipeline shortly before the scheduled
    ``CLEANUP_RANGES`` task fires, so participants can save work off their
    ranges. Returns sent/failed counts like :func:`send_reminder`.
    """
    logger.info("Sending cleanup warning for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    from zoneinfo import ZoneInfo

    tz_name = event.event_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
        tz_name = "UTC"
    cleanup_local = event.get_cleanup_time().astimezone(tz)
    subject = f"{event.name}: ranges will be destroyed soon"
    body = (
        f"The ranges for {event.name} are scheduled for destruction at "
        f"{cleanup_local.strftime('%Y-%m-%d %H:%M')} {tz_name}. "
        "Save anything you need off your range before then; this cannot be undone."
    )

    participants = CTFParticipant.objects.filter(event=event, registered_at__isnull=False).exclude(email="")
    sent = 0
    failed = 0
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
            _send_email(
                recipient=participant.email,
                subject=custom_subject or subject,
                html_content=html_content,
                text_content=text_content,
            )
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Failed to send cleanup warning to %s", safe_log_value(participant.email))

    return {"sent": sent, "failed": failed}


def send_event_results(event_id: UUID) -> dict[str, Any]:
    """Email final results to registered participants at event completion (CTF-801).

    Each recipient gets their own final rank/score/solves plus a short
    top-of-board summary. Best-effort per recipient; hidden and observer
    participants receive the summary without a rank.
    """
    logger.info("Sending event results for event %s", event_id)
    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    from ctf.services.scoring import get_scoreboard

    rows = get_scoreboard(event.pk)
    rank_by_participant = {row["participant_id"]: index + 1 for index, row in enumerate(rows)}
    top_summary = "; ".join(f"{index + 1}. {row['name']} ({row['score']})" for index, row in enumerate(rows[:5]))

    participants = CTFParticipant.objects.filter(event=event, registered_at__isnull=False).exclude(email="")
    sent = 0
    failed = 0
    for participant in participants:
        rank = rank_by_participant.get(str(participant.pk))
        try:
            html_content, text_content, custom_subject = _render_email(
                "event_results",
                {
                    "event": event,
                    "participant": participant,
                    "final_rank": rank if rank is not None else "—",
                    "final_score": participant.cached_score,
                    "solve_count": participant.cached_solve_count,
                    "top_summary": top_summary,
                },
                event=event,
            )
            _send_email(
                recipient=participant.email,
                subject=custom_subject or f"{event.name}: final results",
                html_content=html_content,
                text_content=text_content,
            )
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Failed to send results to %s", safe_log_value(participant.email))

    _record_notification(
        event,
        NotificationType.EVENT_RESULTS.value,
        f"{event.name}: final results",
        sent,
    )
    return {"sent": sent, "failed": failed}


def send_range_ready(participant_id: UUID) -> bool:
    """Tell one participant their range is ready (CTF-801), best-effort."""
    participant = (
        CTFParticipant.objects.select_related("event").filter(pk=participant_id, deleted_at__isnull=True).first()
    )
    if participant is None or not participant.email:
        return False
    event = participant.event
    try:
        from django.conf import settings
        from django.urls import reverse

        base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
        access_url = f"{base}{reverse('ctf:participant_range')}"
        html_content, text_content, custom_subject = _render_email(
            "range_ready",
            {"event": event, "participant": participant, "access_url": access_url},
            event=event,
        )
        _send_email(
            recipient=participant.email,
            subject=custom_subject or f"{event.name}: your range is ready",
            html_content=html_content,
            text_content=text_content,
        )
    except Exception:
        logger.exception("Failed to send range-ready notice to %s", safe_log_value(participant.email))
        return False
    return True


def notify_participant_provision_failure(participant_id: UUID) -> bool:
    """Tell one participant their range hit a provisioning problem (CTF-801)."""
    participant = (
        CTFParticipant.objects.select_related("event").filter(pk=participant_id, deleted_at__isnull=True).first()
    )
    if participant is None or not participant.email:
        return False
    event = participant.event
    try:
        html_content, text_content, custom_subject = _render_email(
            "provision_failure_participant",
            {"event": event, "participant": participant},
            event=event,
        )
        _send_email(
            recipient=participant.email,
            subject=custom_subject or f"{event.name}: a problem with your range",
            html_content=html_content,
            text_content=text_content,
        )
    except Exception:
        logger.exception("Failed to send provision-failure notice to %s", safe_log_value(participant.email))
        return False
    return True


def _record_notification(event: CTFEvent, notification_type: str, subject: str, sent_count: int) -> None:
    """Write the audit row for an automatic notification burst."""
    from django.utils import timezone

    CTFNotification.objects.create(
        event=event,
        notification_type=notification_type,
        subject=subject,
        body=subject,
        status=NotificationStatus.SENT.value,
        recipient_filter="participants",
        sent_count=sent_count,
        sent_at=timezone.now(),
        created_by=event.created_by,
    )
