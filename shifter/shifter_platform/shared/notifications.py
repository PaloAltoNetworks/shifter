"""Shared WebSocket notification registry, queue, and publisher."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.channels.groups import notification_user_topic_group
from shared.models import WebSocketNotification

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

logger = logging.getLogger(__name__)

_TOPIC_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")

PayloadHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
SubscriptionAuthorizer = Callable[[Any, str], bool]


@dataclass(frozen=True)
class NotificationRegistration:
    """Registered notification type and its topic authorization contract."""

    name: str
    topic_prefix: str
    can_subscribe: SubscriptionAuthorizer
    payload_handler: PayloadHandler


_registry: dict[str, NotificationRegistration] = {}


def _identity_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a shallow JSON-style payload copy."""
    return dict(payload)


def validate_topic(topic: str) -> str:
    """Validate and normalize a logical notification topic."""
    if not isinstance(topic, str) or not _TOPIC_RE.fullmatch(topic):
        raise ValueError("notification topic must match ^[a-z][a-z0-9_.:-]{0,127}$")
    return topic


def _validate_notification_type(notification_type: str) -> str:
    """Validate and return a registered notification type name."""
    if not isinstance(notification_type, str) or not _TYPE_RE.fullmatch(notification_type):
        raise ValueError("notification type must match ^[a-z][a-z0-9_.:-]{0,127}$")
    return notification_type


def register_notification_type(
    *,
    name: str,
    topic_prefix: str,
    can_subscribe: SubscriptionAuthorizer,
    payload_handler: PayloadHandler | None = None,
    replace: bool = False,
) -> NotificationRegistration:
    """Register a browser notification type and topic authorizer."""
    name = _validate_notification_type(name)
    topic_prefix = validate_topic(topic_prefix)
    if not callable(can_subscribe):
        raise TypeError("can_subscribe must be callable")
    handler = payload_handler or _identity_payload
    if not callable(handler):
        raise TypeError("payload_handler must be callable")

    existing = _registry.get(name)
    if existing is not None and not replace:
        return existing

    registration = NotificationRegistration(
        name=name,
        topic_prefix=topic_prefix,
        can_subscribe=can_subscribe,
        payload_handler=handler,
    )
    _registry[name] = registration
    return registration


def clear_notification_registry() -> None:
    """Clear registered notification types for tests."""
    _registry.clear()


def _registrations_for_topic(topic: str) -> list[NotificationRegistration]:
    """Return the registrations whose topic prefix matches ``topic``."""
    topic = validate_topic(topic)
    return [registration for registration in _registry.values() if topic.startswith(registration.topic_prefix)]


def authorize_subscription(user: AbstractBaseUser | AnonymousUser, topic: str) -> bool:
    """Return whether a user may subscribe to a logical topic."""
    if not getattr(user, "is_authenticated", False):
        return False
    try:
        registrations = _registrations_for_topic(topic)
    except ValueError:
        return False

    authorized = False
    for registration in registrations:
        try:
            if registration.can_subscribe(user, topic):
                authorized = True
                break
        except Exception:
            logger.warning(
                "notification authorizer failed: type=%s topic=%s user_id=%s",
                registration.name,
                topic,
                getattr(user, "id", None),
                exc_info=True,
            )
    return authorized


def _registration_for_publish(notification_type: str, topic: str) -> NotificationRegistration:
    """Return the registration for a publish call, validating type/topic compatibility."""
    notification_type = _validate_notification_type(notification_type)
    topic = validate_topic(topic)
    try:
        registration = _registry[notification_type]
    except KeyError as exc:
        raise ValueError(f"unknown notification type: {notification_type}") from exc
    if not topic.startswith(registration.topic_prefix):
        raise ValueError(f"topic {topic!r} is not valid for notification type {notification_type!r}")
    return registration


def _coerce_event_id(event_id: uuid.UUID | str | None) -> uuid.UUID:
    """Normalize an optional event id into a UUID, generating one when absent."""
    if event_id is None:
        return uuid.uuid4()
    if isinstance(event_id, uuid.UUID):
        return event_id
    return uuid.UUID(str(event_id))


def _expires_at() -> datetime:
    """Return the retention cutoff for a newly created notification."""
    retention_days = int(getattr(settings, "WEBSOCKET_NOTIFICATION_RETENTION_DAYS", 7))
    return timezone.now() + timedelta(days=max(retention_days, 1))


def _max_replay() -> int:
    """Return the bounded replay-queue size for pending notifications."""
    return max(int(getattr(settings, "WEBSOCKET_NOTIFICATION_MAX_REPLAY", 100)), 1)


def _unique_recipient_ids(recipient_ids: Iterable[int]) -> list[int]:
    """Return recipient ids de-duplicated while preserving first-seen order."""
    seen: set[int] = set()
    unique: list[int] = []
    for recipient_id in recipient_ids:
        normalized = int(recipient_id)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _get_or_create_notification(
    *,
    recipient_id: int,
    notification_type: str,
    topic: str,
    event_id: uuid.UUID,
    payload: dict[str, Any],
    expires_at: datetime,
) -> WebSocketNotification:
    """Idempotently fetch-or-create the per-recipient notification row."""
    try:
        with transaction.atomic():
            notification, _created = WebSocketNotification.objects.get_or_create(
                recipient_id=recipient_id,
                topic=topic,
                notification_type=notification_type,
                event_id=event_id,
                defaults={
                    "payload": payload,
                    "expires_at": expires_at,
                },
            )
    except IntegrityError:
        notification = WebSocketNotification.objects.get(
            recipient_id=recipient_id,
            topic=topic,
            notification_type=notification_type,
            event_id=event_id,
        )
    return notification


def publish_notification(
    notification_type: str,
    *,
    topic: str,
    payload: Mapping[str, Any],
    recipient_ids: Iterable[int],
    event_id: uuid.UUID | str | None = None,
) -> list[WebSocketNotification]:
    """Persist and fan out a browser notification to recipient topic groups."""
    registration = _registration_for_publish(notification_type, topic)
    projected_payload = dict(registration.payload_handler(dict(payload)))
    normalized_event_id = _coerce_event_id(event_id)
    expiration = _expires_at()
    notifications = [
        _get_or_create_notification(
            recipient_id=recipient_id,
            notification_type=notification_type,
            topic=topic,
            event_id=normalized_event_id,
            payload=projected_payload,
            expires_at=expiration,
        )
        for recipient_id in _unique_recipient_ids(recipient_ids)
    ]

    channel_layer = get_channel_layer()
    if channel_layer is not None:
        send = async_to_sync(channel_layer.group_send)
        for notification in notifications:
            send(
                notification_user_topic_group(notification.recipient_id, topic),
                {
                    "type": "notification.dispatch",
                    "notification_id": notification.id,
                },
            )
    return notifications


def pending_notifications_for(user_id: int, topic: str) -> list[WebSocketNotification]:
    """Return the bounded undelivered replay queue for a user/topic."""
    topic = validate_topic(topic)
    return list(
        WebSocketNotification.objects.filter(
            recipient_id=int(user_id),
            topic=topic,
            delivered_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).order_by("created_at", "id")[: _max_replay()]
    )


def mark_notification_delivered(notification_id: int, user_id: int) -> None:
    """Mark one queued notification delivered for the recipient."""
    WebSocketNotification.objects.filter(
        id=notification_id,
        recipient_id=int(user_id),
        delivered_at__isnull=True,
    ).update(delivered_at=timezone.now())


def prune_expired_notifications() -> int:
    """Delete expired notification queue rows and return the count."""
    deleted, _details = WebSocketNotification.objects.filter(expires_at__lte=timezone.now()).delete()
    return deleted
