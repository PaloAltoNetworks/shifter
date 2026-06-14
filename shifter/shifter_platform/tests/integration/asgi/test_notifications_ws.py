"""Real-stack notification websocket integration tests (#924, TEST-6).

Drives ``config.asgi.application`` through ``WebsocketCommunicator`` to the
``SharedNotificationConsumer``: authentication, origin validation, topic
subscription/authorization, live fan-out through the real channel layer (in
both the in-memory and Redis postures), pending-notification replay, and clean
disconnect. The channel layer is never mocked.

The live in-memory fan-out test drives ``channel_layer.group_send`` directly on
the test's event loop because ``publish_notification`` wraps ``group_send`` in
``async_to_sync`` (illegal from a running loop) and the in-memory layer's queues
are loop-bound. The Redis fan-out test exercises the full ``publish_notification``
path (persist + fan-out) offloaded via ``sync_to_async``, which Redis delivers
across the resulting loops. Together they cover both fan-out semantics honestly.
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator

from shared.channels.groups import notification_user_topic_group
from shared.enums import WebSocketCloseCode

from .conftest import DENY_TOPIC, NOTIFICATION_TOPIC, NOTIFICATION_TYPE, handshake_headers, make_notification

NOTIFICATIONS_PATH = "/ws/notifications/"


async def _connect_subscribed(asgi_application, headers, topic: str = NOTIFICATION_TOPIC) -> WebsocketCommunicator:
    """Connect, subscribe to ``topic``, and consume the subscribe ack."""
    communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=headers)
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.send_json_to({"type": "subscribe", "topic": topic})
    ack = await communicator.receive_json_from()
    assert ack == {"type": "subscribed", "topic": topic}
    return communicator


@pytest.mark.django_db(transaction=True)
class TestNotificationWebsocketRealStack:
    """SharedNotificationConsumer reached through the real composed ASGI app."""

    @pytest.mark.asyncio
    async def test_unauthenticated_closed_not_authenticated(self, asgi_application, anon_headers):
        """An anonymous notification handshake is closed NOT_AUTHENTICATED (4001)."""
        communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=anon_headers)
        connected, code = await communicator.connect()

        assert connected is False
        assert code == WebSocketCloseCode.NOT_AUTHENTICATED
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_authenticated_allowed_origin_accepts(self, asgi_application, ws_headers, in_memory_channel_layer):
        """Authenticated user + allowed Origin → accepted (positive origin control)."""
        communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=ws_headers)
        connected, _ = await communicator.connect()

        assert connected is True
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_disallowed_origin_rejected(self, asgi_application, ws_cookie_value):
        """Authenticated user + cross-origin → denied by AllowedHostsOriginValidator."""
        from .conftest import DISALLOWED_ORIGIN

        headers = handshake_headers(ws_cookie_value, origin=DISALLOWED_ORIGIN)
        communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=headers)
        connected, code = await communicator.connect()

        assert connected is False
        assert code == 1000
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_subscribe_authorized_topic_acks(
        self, asgi_application, ws_headers, registered_notification_type, in_memory_channel_layer
    ):
        """Subscribing to an authorized topic returns a ``subscribed`` ack."""
        communicator = await _connect_subscribed(asgi_application, ws_headers)
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_subscribe_unauthorized_topic_denied(
        self, asgi_application, ws_headers, registered_notification_type, in_memory_channel_layer
    ):
        """Subscribing to a topic whose authorizer denies → PERMISSION_DENIED (4003)."""
        communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=ws_headers)
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "subscribe", "topic": DENY_TOPIC})
        output = await communicator.receive_output()

        assert output["type"] == "websocket.close"
        assert output["code"] == WebSocketCloseCode.PERMISSION_DENIED
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_subscribe_invalid_topic_closed(self, asgi_application, ws_headers, in_memory_channel_layer):
        """A malformed topic string → INVALID_REQUEST (4005)."""
        communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=ws_headers)
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "subscribe", "topic": "INVALID TOPIC!"})
        output = await communicator.receive_output()

        assert output["type"] == "websocket.close"
        assert output["code"] == WebSocketCloseCode.INVALID_REQUEST
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_live_fanout_in_memory(
        self, asgi_application, ws_user, ws_headers, registered_notification_type, in_memory_channel_layer
    ):
        """A group_send through the real in-memory layer reaches the subscriber."""
        communicator = await _connect_subscribed(asgi_application, ws_headers)

        notification = await sync_to_async(make_notification)(ws_user, payload={"msg": "in-memory"})
        group = notification_user_topic_group(ws_user.id, NOTIFICATION_TOPIC)
        await get_channel_layer().group_send(
            group, {"type": "notification.dispatch", "notification_id": notification.id}
        )

        message = await communicator.receive_json_from()
        assert message["type"] == "notification"
        assert message["id"] == notification.id
        assert message["topic"] == NOTIFICATION_TOPIC
        assert message["payload"] == {"msg": "in-memory"}
        await communicator.disconnect()

    @pytest.mark.redis
    @pytest.mark.asyncio
    async def test_live_fanout_redis(
        self, asgi_application, ws_user, ws_headers, registered_notification_type, redis_channel_layer
    ):
        """The full publish_notification path fans out through real Redis."""
        from shared.notifications import publish_notification

        communicator = await _connect_subscribed(asgi_application, ws_headers)

        notifications = await sync_to_async(publish_notification)(
            NOTIFICATION_TYPE,
            topic=NOTIFICATION_TOPIC,
            payload={"msg": "redis"},
            recipient_ids=[ws_user.id],
        )

        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "notification"
        assert message["id"] == notifications[0].id
        assert message["payload"] == {"msg": "redis"}
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_replay_pending_on_subscribe(
        self, asgi_application, ws_user, ws_headers, registered_notification_type, in_memory_channel_layer
    ):
        """Pending undelivered notifications are replayed right after subscribe."""
        pending = await sync_to_async(make_notification)(ws_user, payload={"queued": True})

        communicator = await _connect_subscribed(asgi_application, ws_headers)
        replayed = await communicator.receive_json_from()

        assert replayed["type"] == "notification"
        assert replayed["id"] == pending.id
        assert replayed["payload"] == {"queued": True}
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_clean_disconnect_removes_group_membership(
        self, asgi_application, ws_user, ws_headers, registered_notification_type, in_memory_channel_layer
    ):
        """Disconnect runs group_discard, leaving no stale channel-layer membership."""
        communicator = await _connect_subscribed(asgi_application, ws_headers)

        layer = get_channel_layer()
        group = notification_user_topic_group(ws_user.id, NOTIFICATION_TOPIC)
        assert len(layer.groups.get(group, {})) == 1

        await communicator.disconnect()
        assert len(layer.groups.get(group, {})) == 0
