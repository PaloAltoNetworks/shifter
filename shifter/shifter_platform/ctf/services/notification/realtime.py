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
from uuid import UUID

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

    from ctf.models import CTFEvent

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "ctf_event"
TOPIC_PREFIX = "ctf:event"


def event_topic(event_id: object) -> str:
    """Return the per-event notification topic."""
    return f"{TOPIC_PREFIX}:{event_id}"


def _topic_event(topic: str) -> CTFEvent | None:
    """Resolve a ``ctf:event:<uuid>`` topic to a live event, or None."""
    from uuid import UUID

    from ctf.models import CTFEvent

    try:
        event_id = UUID(topic.rsplit(":", 1)[-1])
    except ValueError:
        return None
    return CTFEvent.objects.filter(pk=event_id, deleted_at__isnull=True).only("id", "created_by_id").first()


def _can_subscribe(user: AbstractBaseUser | AnonymousUser, topic: str) -> bool:
    """Authorize a subscription: event organizer, eligible staff, or viewing participant.

    A live staff row authorizes only while the account still holds the global CTF
    Organizer role (#1922 review — no stale-row bypass).
    """
    from ctf.models import CTFEventStaff, CTFParticipant
    from ctf.services.event.staff import actor_is_active_ctf_organizer
    from ctf.services.participant import viewing_participant_q

    user_id = getattr(user, "pk", None)
    if user_id is None:
        return False
    event = _topic_event(topic)
    if event is None:
        return False
    return (
        event.created_by_id == user_id
        or (
            CTFEventStaff.objects.filter(event=event, user_id=user_id, deleted_at__isnull=True).exists()
            and actor_is_active_ctf_organizer(user_id)
        )
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
            from ctf.services.event.staff import eligible_co_organizer_ids
            from ctf.services.participant import viewing_participant_q

            recipient_ids = list(
                CTFParticipant.objects.filter(viewing_participant_q(), event=event, user_id__isnull=False)
                .values_list("user_id", flat=True)
                .distinct()
            )
            # Organizer-directed recipients are the canonical owner plus live full
            # co-organizers who are still eligible (active + global CTF Organizer
            # role), derived from current assignments and de-duplicated (#1922).
            # Distinct from notification sender/`created_by` attribution;
            # moderators/judges are unchanged.
            recipient_ids.append(event.created_by_id)
            recipient_ids.extend(eligible_co_organizer_ids(event))
            recipient_ids = list(dict.fromkeys(recipient_ids))
        publish_notification(
            NOTIFICATION_TYPE,
            topic=event_topic(event.pk),
            payload={"kind": kind, "event_name": event.name, **payload},
            recipient_ids=recipient_ids,
            event_id=event.pk,
        )
    except Exception:
        logger.exception("Failed to publish %s notification for event %s", kind, event.pk)


def publish_communication_wakeup(
    *,
    event_id: UUID | str,
    recipient_user_id: int,
    snapshot_id: UUID | str,
    references: dict[str, str],
) -> bool:
    """Publish one reference-only in-app communication wake-up, best-effort (#2098).

    The wake-up is an accelerator over the durable inbox (the ``RecipientSnapshot`` /
    ``ParticipantReceipt`` committed at admission), never the source of truth. It
    uses the stable per-recipient ``snapshot_id`` as the shared replay identity so
    distinct communications never collapse onto one row and a replayed wake-up maps
    to the same row (no duplicate visible entries) -- unlike the event-scoped
    ``publish_event_notification``, which keys on the event UUID. It carries only
    identifiers, never message subject, body, recipient PII, or secrets.

    Returns True when a wake-up row was published, False when the subsystem is
    disabled or there is no account recipient to wake.
    """
    from shared.notifications import notifications_enabled, publish_notification

    if not notifications_enabled() or recipient_user_id is None:
        return False
    # Idempotent re-registration (mirrors publish_event_notification): a registry
    # reset or test isolation must not silently drop the wake-up.
    register_ctf_notifications()
    published = publish_notification(
        NOTIFICATION_TYPE,
        topic=event_topic(event_id),
        payload={"kind": "communication", **references},
        recipient_ids=[int(recipient_user_id)],
        event_id=snapshot_id,
    )
    return bool(published)
