"""Tests for RangeStatusConsumer.

Integration-style tests covering the WebSocket consumer lifecycle:
connect, receive status updates, disconnect.
"""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from django.contrib.auth.models import AnonymousUser

from shared.enums import ResourceStatus, WebSocketCloseCode

# Test UUID for request_id
TEST_REQUEST_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TEST_REQUEST_UUID = UUID(TEST_REQUEST_ID)


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
        "url_route": {"kwargs": {"request_id": TEST_REQUEST_ID}},
    }


@pytest.fixture
def unauthenticated_scope():
    """WebSocket scope with anonymous user."""
    return {
        "type": "websocket",
        "user": AnonymousUser(),
        "url_route": {"kwargs": {"request_id": TEST_REQUEST_ID}},
    }


class TestRangeStatusConsumerConnect:
    """Tests for connect() behavior.

    The range-lookup connect paths (success-hydrates-status, not-found,
    other-user) are driven against real ``cms.services.get_range_by_request_id``
    + real DB rows in ``tests/integration/engine/test_consumers_integration.py``
    (``TestRangeStatusConsumerIntegration``), so they are not re-mocked here.
    Only the no-DB unauthenticated guard is unit-tested.
    """

    @pytest.mark.asyncio
    async def test_rejects_unauthenticated_user(self, consumer, unauthenticated_scope):
        """Unauthenticated users are rejected with NOT_AUTHENTICATED."""
        consumer.scope = unauthenticated_scope

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)
        consumer.accept.assert_not_awaited()


class TestRangeStatusConsumerDisconnect:
    """Tests for disconnect() behavior."""

    @pytest.mark.asyncio
    async def test_leaves_channel_group(self, consumer):
        """Disconnect leaves the channel group."""
        consumer.request_id = TEST_REQUEST_ID
        consumer.group_name = f"range_status_{TEST_REQUEST_ID}"

        await consumer.disconnect(close_code=1000)

        consumer.channel_layer.group_discard.assert_awaited_once_with(f"range_status_{TEST_REQUEST_ID}", "test-channel")

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
        consumer.request_id = TEST_REQUEST_ID

        event = {
            "type": "range_status",
            "request_id": TEST_REQUEST_ID,
            "new_status": ResourceStatus.READY.value,
            "error_message": None,
        }
        await consumer.range_status(event)

        consumer.send.assert_awaited_once()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message == {
            "type": "status",
            "request_id": TEST_REQUEST_ID,
            "status": ResourceStatus.READY.value,
            "error_message": None,
        }

    @pytest.mark.asyncio
    async def test_prefers_range_ref_payload(self, consumer):
        """range_status() hydrates from RangeRef when range_ref is present."""
        consumer.request_id = TEST_REQUEST_ID

        event = {
            "type": "range_status",
            "range_ref": {
                "request_id": TEST_REQUEST_ID,
                "range_id": 7,
                "user_id": 42,
                "status": ResourceStatus.PROVISIONING.value,
            },
            "request_id": TEST_REQUEST_ID,
            "new_status": ResourceStatus.READY.value,
            "error_message": None,
        }
        await consumer.range_status(event)

        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["request_id"] == TEST_REQUEST_ID
        assert message["status"] == ResourceStatus.PROVISIONING.value

    @pytest.mark.asyncio
    async def test_includes_error_message_on_failure(self, consumer):
        """range_status() includes error message for failed ranges."""
        consumer.request_id = TEST_REQUEST_ID

        event = {
            "type": "range_status",
            "request_id": TEST_REQUEST_ID,
            "new_status": ResourceStatus.FAILED.value,
            "error_message": "EC2 limit exceeded",
        }
        await consumer.range_status(event)

        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["status"] == ResourceStatus.FAILED.value
        assert message["error_message"] == "EC2 limit exceeded"
