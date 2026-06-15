"""Tests for the shared notification WebSocket consumer."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from shared.channels.groups import notification_user_topic_group
from shared.enums import WebSocketCloseCode
from shared.models import WebSocketNotification


@pytest.fixture(autouse=True)
def clear_notification_registry():
    """Keep notification registrations isolated between tests."""
    from shared.notifications import clear_notification_registry

    clear_notification_registry()
    yield
    clear_notification_registry()


@pytest.fixture
def user(db):
    """Create a test user."""
    return get_user_model().objects.create_user(username="owner@example.com", email="owner@example.com")


def _register_authorized_topic() -> None:
    from shared.notifications import register_notification_type

    register_notification_type(
        name="experiment.run_status",
        topic_prefix="experiment:",
        can_subscribe=lambda _user, _topic: True,
    )


@pytest.fixture
def consumer():
    """Create a notification consumer with mocked WebSocket methods."""
    from shared.consumers import SharedNotificationConsumer

    c = SharedNotificationConsumer()
    c.channel_name = "test-channel"
    c.channel_layer = AsyncMock()
    c.close = AsyncMock()
    c.accept = AsyncMock()
    c.send = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_rejects_anonymous_user(consumer):
    """Anonymous users cannot open the shared notification socket."""
    consumer.scope = {"type": "websocket", "user": AnonymousUser()}

    await consumer.connect()

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)
    consumer.accept.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_before_auth_returns_without_group_updates(consumer):
    """Disconnect is a no-op when the socket never authenticated."""
    await consumer.disconnect(close_code=1000)

    consumer.channel_layer.group_discard.assert_not_awaited()
    assert consumer.subscriptions == set()


@pytest.mark.asyncio
async def test_disconnect_discards_all_subscription_groups(consumer, user):
    """Disconnect leaves every joined notification group."""
    consumer._user_id = user.id
    consumer.subscriptions = {"experiment:100", "experiment:200"}

    await consumer.disconnect(close_code=1000)

    discarded_groups = {call.args[0] for call in consumer.channel_layer.group_discard.await_args_list}
    assert discarded_groups == {
        notification_user_topic_group(user.id, "experiment:100"),
        notification_user_topic_group(user.id, "experiment:200"),
    }
    assert consumer.subscriptions == set()


@pytest.mark.asyncio
async def test_receive_ignores_empty_messages_and_rejects_invalid_json(consumer):
    """Raw WebSocket messages must be JSON control envelopes."""
    await consumer.receive(text_data=None)
    consumer.close.assert_not_awaited()

    await consumer.receive(text_data="{")

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)


@pytest.mark.asyncio
async def test_receive_dispatches_valid_json_control_message(consumer):
    """Raw JSON messages are delegated to the JSON control handler."""
    consumer.receive_json = AsyncMock()

    await consumer.receive(text_data='{"type": "subscribe", "topic": "experiment:100"}')

    consumer.receive_json.assert_awaited_once_with({"type": "subscribe", "topic": "experiment:100"})


@pytest.mark.asyncio
async def test_receive_json_rejects_unknown_control_message(consumer):
    """Only subscribe and unsubscribe control messages are accepted."""
    await consumer.receive_json({"type": "ping", "topic": "experiment:100"})

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)


@pytest.mark.asyncio
async def test_subscribe_before_auth_closes(consumer):
    """Subscribe cannot proceed before connect establishes the user id."""
    await consumer.receive_json({"type": "subscribe", "topic": "experiment:100"})

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)


@pytest.mark.asyncio
async def test_subscribe_rejects_invalid_topic(consumer, user):
    """Invalid topic syntax closes the socket."""
    consumer.scope = {"type": "websocket", "user": user}
    await consumer.connect()

    await consumer.receive_json({"type": "subscribe", "topic": "not valid"})

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_subscribe_replays_pending_notifications_and_marks_delivered(consumer, user, settings):
    """Subscribing joins the user/topic group and replays missed notifications."""
    _register_authorized_topic()
    settings.WEBSOCKET_NOTIFICATION_MAX_REPLAY = 10
    pending = await database_sync_to_async(WebSocketNotification.objects.create)(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"run_id": 7, "status": "running"},
        expires_at=timezone.now() + timedelta(days=1),
    )
    consumer.scope = {"type": "websocket", "user": user}

    await consumer.connect()
    await consumer.receive_json({"type": "subscribe", "topic": "experiment:100"})

    consumer.channel_layer.group_add.assert_awaited_once()
    assert consumer.channel_layer.group_add.await_args.args == (
        notification_user_topic_group(user.id, "experiment:100"),
        "test-channel",
    )
    sent_messages = [call.kwargs["text_data"] for call in consumer.send.await_args_list]
    assert any('"type": "subscribed"' in message for message in sent_messages)
    assert any('"type": "notification"' in message and '"run_id": 7' in message for message in sent_messages)
    await database_sync_to_async(pending.refresh_from_db)()
    assert pending.delivered_at is not None


@pytest.mark.asyncio
async def test_unsubscribe_discards_known_topic_and_confirms(consumer, user):
    """Unsubscribe leaves a joined topic group and sends an acknowledgement."""
    consumer.scope = {"type": "websocket", "user": user}
    await consumer.connect()
    consumer.subscriptions = {"experiment:100"}

    await consumer.receive_json({"type": "unsubscribe", "topic": "experiment:100"})

    consumer.channel_layer.group_discard.assert_awaited_once_with(
        notification_user_topic_group(user.id, "experiment:100"),
        "test-channel",
    )
    payload = json.loads(consumer.send.await_args.kwargs["text_data"])
    assert payload == {"type": "unsubscribed", "topic": "experiment:100"}


@pytest.mark.asyncio
async def test_unsubscribe_without_user_returns(consumer):
    """Unsubscribe is a no-op before authentication."""
    await consumer.receive_json({"type": "unsubscribe", "topic": "experiment:100"})

    consumer.send.assert_not_awaited()
    consumer.channel_layer.group_discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsubscribe_rejects_invalid_topic(consumer, user):
    """Invalid unsubscribe topics close the socket."""
    consumer.scope = {"type": "websocket", "user": user}
    await consumer.connect()

    await consumer.receive_json({"type": "unsubscribe", "topic": "not valid"})

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)


@pytest.mark.asyncio
async def test_replay_pending_without_user_returns(consumer):
    """Replay cannot query without an authenticated user id."""
    await consumer._replay_pending("experiment:100")

    consumer.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_notification_without_user_returns_none(consumer):
    """Notification lookup cannot query before authentication."""
    assert await consumer._get_notification(1) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_live_dispatch_sends_notification_and_marks_delivered(consumer, user):
    """Live dispatch sends a stored notification for an active subscription."""
    _register_authorized_topic()
    notification = await database_sync_to_async(WebSocketNotification.objects.create)(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"run_id": 8, "status": "completed"},
        expires_at=timezone.now() + timedelta(days=1),
    )
    consumer.scope = {"type": "websocket", "user": user}
    consumer.subscriptions = {"experiment:100"}
    consumer._user_id = user.id

    await consumer.notification_dispatch(
        {
            "type": "notification.dispatch",
            "notification_id": notification.id,
        }
    )

    consumer.send.assert_awaited_once()
    assert '"run_id": 8' in consumer.send.await_args.kwargs["text_data"]
    await database_sync_to_async(notification.refresh_from_db)()
    assert notification.delivered_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_live_dispatch_ignores_unusable_notifications(consumer, user):
    """Live dispatch ignores unauthenticated, missing, unsubscribed, and expired rows."""
    notification = await database_sync_to_async(WebSocketNotification.objects.create)(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"run_id": 8, "status": "completed"},
        expires_at=timezone.now() + timedelta(days=1),
    )
    expired = await database_sync_to_async(WebSocketNotification.objects.create)(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"run_id": 9, "status": "expired"},
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    await consumer.notification_dispatch({"notification_id": notification.id})
    consumer.send.assert_not_awaited()

    consumer._user_id = user.id
    await consumer.notification_dispatch({"notification_id": "not-an-id"})
    await consumer.notification_dispatch({"notification_id": notification.id})

    consumer.subscriptions = {"experiment:100"}
    await consumer.notification_dispatch({"notification_id": expired.id})

    consumer.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_notification_without_user_returns(consumer, user):
    """Notification send is guarded by the authenticated user id."""
    notification = WebSocketNotification(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"run_id": 8, "status": "completed"},
        expires_at=timezone.now() + timedelta(days=1),
    )

    await consumer._send_notification(notification)

    consumer.send.assert_not_awaited()


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_rejects_unauthorized_subscription(consumer):
    """A registered topic must authorize the current user before subscription."""
    from shared.notifications import register_notification_type

    register_notification_type(
        name="experiment.run_status",
        topic_prefix="experiment:",
        can_subscribe=lambda _user, _topic: False,
    )
    user = MagicMock(id=42, is_authenticated=True)
    consumer.scope = {"type": "websocket", "user": user}

    await consumer.connect()
    await consumer.receive_json({"type": "subscribe", "topic": "experiment:100"})

    consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.PERMISSION_DENIED)


def test_shared_notification_websocket_route_targets_consumer():
    """Shared notification route exposes the generic consumer."""
    from shared.routing import websocket_urlpatterns

    assert websocket_urlpatterns
    assert websocket_urlpatterns[0].pattern.regex.pattern == "ws/notifications/$"
