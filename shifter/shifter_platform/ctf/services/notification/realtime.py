"""Real-time in-app notifications over the shared WebSocket bus (CTF-802).

CTF publishes event-scoped browser notifications through
:mod:`shared.notifications` (PLAT-105): one notification type
(``ctf_event``) on per-event topics ``ctf:event:<uuid>``. Subscription is
authorized for the event's viewing participants, staff, and the owning
organizer. Publishing is best-effort — a bus outage never affects the
triggering action — and disconnected participants receive pending
notifications on their next connection (shared-bus replay).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

    from ctf.models import CTFEvent

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "ctf_event"
TOPIC_PREFIX = "ctf:event"


def event_topic(event_id: object) -> str:
    """Return the per-event notification topic."""
    return f"{TOPIC_PREFIX}:{event_id}"


def _can_subscribe(user: AbstractBaseUser | AnonymousUser, topic: str) -> bool:
    """Authorize a subscription: event organizer, staff, or viewing participant."""
    from uuid import UUID

    from ctf.models import CTFEvent, CTFEventStaff, CTFParticipant
    from ctf.services.participant import viewing_participant_q

    user_id = getattr(user, "pk", None)
    if user_id is None:
        return False
    try:
        event_id = UUID(topic.rsplit(":", 1)[-1])
    except ValueError:
        return False
    event = CTFEvent.objects.filter(pk=event_id, deleted_at__isnull=True).only("id", "created_by_id").first()
    return event is not None and (
        event.created_by_id == user_id
        or CTFEventStaff.objects.filter(event=event, user_id=user_id, deleted_at__isnull=True).exists()
        or CTFParticipant.objects.filter(viewing_participant_q(), event=event, user_id=user_id).exists()
    )


def register_ctf_notifications() -> None:
    """Register the CTF notification type with the shared bus (idempotent)."""
    from shared.notifications import register_notification_type

    register_notification_type(
        name=NOTIFICATION_TYPE,
        topic_prefix=TOPIC_PREFIX,
        can_subscribe=_can_subscribe,
    )


def publish_event_notification(
    event: CTFEvent,
    kind: str,
    payload: dict[str, Any],
    *,
    recipient_ids: list[int] | None = None,
) -> None:
    """Publish one event-scoped browser notification, best-effort.

    ``recipient_ids`` narrows delivery (e.g. a single participant's
    range-ready notice); by default every viewing participant with an
    account plus the organizer receives it.
    """
    from shared.notifications import notifications_enabled, publish_notification

    try:
        if not notifications_enabled():
            return
        # Idempotent re-registration: registration normally happens in
        # apps.ready, but test isolation (and any future registry reset)
        # must not silently drop CTF publishes.
        register_ctf_notifications()
        if recipient_ids is None:
            from ctf.models import CTFParticipant
            from ctf.services.participant import viewing_participant_q

            recipient_ids = list(
                CTFParticipant.objects.filter(viewing_participant_q(), event=event, user_id__isnull=False)
                .values_list("user_id", flat=True)
                .distinct()
            )
            recipient_ids.append(event.created_by_id)
        publish_notification(
            NOTIFICATION_TYPE,
            topic=event_topic(event.pk),
            payload={"kind": kind, "event_name": event.name, **payload},
            recipient_ids=recipient_ids,
            event_id=event.pk,
        )
    except Exception:
        logger.exception("Failed to publish %s notification for event %s", kind, event.pk)
