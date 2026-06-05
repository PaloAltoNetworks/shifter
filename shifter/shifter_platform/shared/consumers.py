"""Shared WebSocket consumers."""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from shared.channels.groups import notification_user_topic_group
from shared.enums import WebSocketCloseCode
from shared.models import WebSocketNotification
from shared.notifications import (
    authorize_subscription,
    mark_notification_delivered,
    pending_notifications_for,
    validate_topic,
)

logger = logging.getLogger(__name__)


class SharedNotificationConsumer(AsyncWebsocketConsumer):
    """Authenticated topic-subscription consumer for browser notifications."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.subscriptions: set[str] = set()
        self._user_id: int | None = None

    async def connect(self) -> None:
        """Accept authenticated notification sockets."""
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
            logger.warning("Unauthenticated notification WebSocket connection attempt")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

        self._user_id = int(user.id)
        self.subscriptions = set()
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Leave all subscribed topic groups."""
        if self._user_id is None:
            return
        for topic in self.subscriptions:
            await self.channel_layer.group_discard(
                notification_user_topic_group(self._user_id, topic),
                self.channel_name,
            )
        self.subscriptions.clear()

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        """Parse incoming JSON control messages."""
        if not text_data:
            return
        try:
            content = json.loads(text_data)
        except json.JSONDecodeError:
            await self.close(code=WebSocketCloseCode.INVALID_REQUEST)
            return
        await self.receive_json(content)

    async def receive_json(self, content: dict[str, Any]) -> None:
        """Handle subscription control messages."""
        message_type = content.get("type")
        topic = content.get("topic")
        if message_type == "subscribe" and isinstance(topic, str):
            await self._subscribe(topic)
        elif message_type == "unsubscribe" and isinstance(topic, str):
            await self._unsubscribe(topic)
        else:
            await self.close(code=WebSocketCloseCode.INVALID_REQUEST)

    async def _subscribe(self, topic: str) -> None:
        """Authorize, join, and replay a logical topic."""
        if self._user_id is None:
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return
        try:
            topic = validate_topic(topic)
        except ValueError:
            await self.close(code=WebSocketCloseCode.INVALID_REQUEST)
            return
        if not await database_sync_to_async(authorize_subscription)(self.scope["user"], topic):
            await self.close(code=WebSocketCloseCode.PERMISSION_DENIED)
            return

        self.subscriptions.add(topic)
        await self.channel_layer.group_add(
            notification_user_topic_group(self._user_id, topic),
            self.channel_name,
        )
        await self.send(text_data=json.dumps({"type": "subscribed", "topic": topic}))
        await self._replay_pending(topic)

    async def _unsubscribe(self, topic: str) -> None:
        """Leave a logical topic."""
        if self._user_id is None:
            return
        try:
            topic = validate_topic(topic)
        except ValueError:
            await self.close(code=WebSocketCloseCode.INVALID_REQUEST)
            return
        if topic in self.subscriptions:
            self.subscriptions.remove(topic)
            await self.channel_layer.group_discard(
                notification_user_topic_group(self._user_id, topic),
                self.channel_name,
            )
        await self.send(text_data=json.dumps({"type": "unsubscribed", "topic": topic}))

    async def _replay_pending(self, topic: str) -> None:
        """Replay pending notifications for a subscribed topic."""
        if self._user_id is None:
            return
        notifications = await database_sync_to_async(pending_notifications_for)(self._user_id, topic)
        for notification in notifications:
            await self._send_notification(notification)

    async def notification_dispatch(self, event: dict[str, Any]) -> None:
        """Handle live notification dispatch from the channel layer."""
        if self._user_id is None:
            return
        notification = await self._get_notification(event.get("notification_id"))
        if notification is None or notification.topic not in self.subscriptions:
            return
        if notification.expires_at <= timezone.now():
            return
        await self._send_notification(notification)

    async def _send_notification(self, notification: WebSocketNotification) -> None:
        """Send a notification payload and mark it delivered after success."""
        if self._user_id is None:
            return
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification",
                    "id": notification.id,
                    "event_id": str(notification.event_id),
                    "notification_type": notification.notification_type,
                    "topic": notification.topic,
                    "payload": notification.payload,
                    "created_at": notification.created_at.isoformat(),
                },
                default=str,
            )
        )
        await database_sync_to_async(mark_notification_delivered)(notification.id, self._user_id)

    @database_sync_to_async
    def _get_notification(self, notification_id: Any) -> WebSocketNotification | None:
        """Fetch a notification belonging to this connection's user."""
        if self._user_id is None:
            return None
        try:
            return WebSocketNotification.objects.get(id=notification_id, recipient_id=self._user_id)
        except (TypeError, ValueError, WebSocketNotification.DoesNotExist):
            return None
