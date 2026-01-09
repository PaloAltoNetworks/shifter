"""Tests for RangeStatusConsumer.

Integration-style tests covering the WebSocket consumer lifecycle:
connect, receive status updates, disconnect.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser

from shared.enums import ResourceStatus, WebSocketCloseCode


@pytest.fixture
def consumer():
    """Create a RangeStatusConsumer with mocked WebSocket methods."""
    from mission_control.consumers import RangeStatusConsumer

    c = RangeStatusConsumer()
    c.channel_name = "test-channel"
    c.channel_layer = AsyncMock()
    c.close = AsyncMock()
    c.accept = AsyncMock()
    c.send = AsyncMock()
    return c


@pytest.fixture
def authenticated_scope():
    """WebSocket scope with authenticated user."""
    user = MagicMock()
    user.id = 1
    user.is_authenticated = True
    return {
        "type": "websocket",
        "user": user,
        "url_route": {"kwargs": {"range_id": "42"}},
    }


@pytest.fixture
def unauthenticated_scope():
    """WebSocket scope with anonymous user."""
    return {
        "type": "websocket",
        "user": AnonymousUser(),
        "url_route": {"kwargs": {"range_id": "42"}},
    }


class TestRangeStatusConsumerConnect:
    """Tests for connect() behavior."""

    @pytest.mark.asyncio
    async def test_rejects_unauthenticated_user(self, consumer, unauthenticated_scope):
        """Unauthenticated users are rejected with NOT_AUTHENTICATED."""
        consumer.scope = unauthenticated_scope

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)
        consumer.accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_when_range_not_found(self, consumer, authenticated_scope):
        """Returns NOT_FOUND when CMS raises error."""
        from shared.exceptions import CMSError

        consumer.scope = authenticated_scope

        with patch("cms.get_range", side_effect=CMSError("Not found")):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    @pytest.mark.asyncio
    async def test_accepts_and_hydrates_on_success(self, consumer, authenticated_scope):
        """Successful connect accepts WebSocket and sends initial status."""
        consumer.scope = authenticated_scope
        mock_range = MagicMock(status=ResourceStatus.READY.value)

        with patch("cms.get_range", return_value=mock_range):
            await consumer.connect()

        # Should accept connection
        consumer.accept.assert_awaited_once()

        # Should join channel group
        consumer.channel_layer.group_add.assert_awaited_once()

        # Should send initial status (hydration)
        consumer.send.assert_awaited_once()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["type"] == "status"
        assert message["range_id"] == 42
        assert message["status"] == ResourceStatus.READY.value


class TestRangeStatusConsumerDisconnect:
    """Tests for disconnect() behavior."""

    @pytest.mark.asyncio
    async def test_leaves_channel_group(self, consumer):
        """Disconnect leaves the channel group."""
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        await consumer.disconnect(close_code=1000)

        consumer.channel_layer.group_discard.assert_awaited_once_with("range_status_42", "test-channel")

    @pytest.mark.asyncio
    async def test_handles_disconnect_without_connect(self, consumer):
        """Disconnect handles case where connect never completed."""
        consumer.group_name = None

        await consumer.disconnect(close_code=1000)

        consumer.channel_layer.group_discard.assert_not_awaited()


class TestRangeStatusConsumerRangeStatus:
    """Tests for range_status() event handler."""

    @pytest.mark.asyncio
    async def test_sends_status_update(self, consumer):
        """range_status() sends formatted status update to WebSocket."""
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": ResourceStatus.READY.value,
            "error_message": None,
        }
        await consumer.range_status(event)

        consumer.send.assert_awaited_once()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message == {
            "type": "status",
            "range_id": 42,
            "status": ResourceStatus.READY.value,
            "error_message": None,
        }

    @pytest.mark.asyncio
    async def test_includes_error_message_on_failure(self, consumer):
        """range_status() includes error message for failed ranges."""
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": ResourceStatus.FAILED.value,
            "error_message": "EC2 limit exceeded",
        }
        await consumer.range_status(event)

        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["status"] == ResourceStatus.FAILED.value
        assert message["error_message"] == "EC2 limit exceeded"
