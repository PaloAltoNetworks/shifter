"""Cleanup-warning notification (CTF-1003).

Split from the former ``notification`` module and re-exported through
``ctf.services.notification``. The email helpers (``_send_email`` /
``_render_email``) are resolved through the package at call time
(``from ctf.services import notification as _n``) so tests that patch
``ctf.services.notification._send_email`` are honoured (see the package
docstring's PATCH LOCALITY note).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFParticipant
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def send_cleanup_warning(event_id: UUID) -> dict[str, Any]:
    """Warn registered participants that range destruction is imminent (CTF-1003).

    Delivered through the announcement pipeline shortly before the scheduled
    ``CLEANUP_RANGES`` task fires, so participants can save work off their
    ranges. Returns sent/failed counts like :func:`send_reminder`.
    """
    from ctf.services import notification as _n

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
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Failed to send cleanup warning to %s", safe_log_value(participant.email))

    return {"sent": sent, "failed": failed}
