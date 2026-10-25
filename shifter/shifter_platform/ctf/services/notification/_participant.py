"""Non-secret participant notices; legacy send writes are retired."""

from __future__ import annotations

from uuid import UUID

from ctf.services.notification._scheduled import retired_write
from ctf.services.notification.ledger import stage_notice

send_announcement = retired_write
schedule_notification = retired_write
send_login_info = retired_write
send_credentials = retired_write


def send_reminder(event_id: UUID, hours_before: int = 24) -> dict[str, str]:
    """Stage one non-secret reminder for the event start occurrence."""

    from ctf.models import CTFEvent

    event = CTFEvent.objects.get(pk=event_id)
    return stage_notice(
        event_id,
        kind="reminder",
        subject="Event reminder",
        body="Your event starts soon. Open the event page for the current schedule.",
        occurrence=f"{event.event_start.isoformat()}:{hours_before}",
    )
