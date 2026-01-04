"""Tests for RangeStatusConsumer.connect.

Tests the WebSocket connection handler for range status updates.

Contract being tested:
- Inputs: WebSocket connection request (implicit via scope)
- Outputs: None (async method)
- Side effects:
  - Closes with NOT_AUTHENTICATED if user not authenticated
  - Closes with NOT_FOUND if range not found/not owned
  - Joins channel group for range updates
  - Accepts WebSocket connection
  - Sends initial status hydration message
- Errors: CMSError from get_range results in NOT_FOUND close
- Logging: Logs warning on auth failure, info on successful connect
"""

import json
from unittest.mock import patch

import pytest

from shared.enums import RangeStatus, WebSocketCloseCode
from shared.exceptions import CMSError


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectAuthentication:
    """Tests for RangeStatusConsumer.connect authentication handling."""

    # -------------------------------------------------------------------------
    # Authentication - user verification
    # -------------------------------------------------------------------------

    async def test_closes_with_not_authenticated_when_user_is_none(self, range_status_consumer_factory):
        """connect() closes with NOT_AUTHENTICATED when user is None."""
        scope = {
            "type": "websocket",
            "user": None,
            "url_route": {"kwargs": {"range_id": "42"}},
        }
        consumer = range_status_consumer_factory(scope)

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    async def test_closes_with_not_authenticated_for_anonymous_user(
        self, range_status_consumer_factory, anonymous_user
    ):
        """connect() closes with NOT_AUTHENTICATED for AnonymousUser."""
        scope = {
            "type": "websocket",
            "user": anonymous_user,
            "url_route": {"kwargs": {"range_id": "42"}},
        }
        consumer = range_status_consumer_factory(scope)

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    async def test_logs_warning_for_unauthenticated_attempt(self, range_status_consumer_factory, anonymous_user):
        """connect() logs warning for unauthenticated connection attempt."""
        scope = {
            "type": "websocket",
            "user": anonymous_user,
            "url_route": {"kwargs": {"range_id": "42"}},
        }
        consumer = range_status_consumer_factory(scope)

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "Unauthenticated" in call_args or "unauthenticated" in call_args.lower()


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectRangeValidation:
    """Tests for RangeStatusConsumer.connect range validation."""

    # -------------------------------------------------------------------------
    # Range lookup - CMS interaction
    # -------------------------------------------------------------------------

    async def test_closes_with_not_found_when_range_not_found(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """connect() closes with NOT_FOUND when range not found."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", side_effect=CMSError("Not found")):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_closes_with_not_found_when_permission_denied(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """connect() closes with NOT_FOUND when user doesn't own range."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", side_effect=CMSError("Permission denied")):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_logs_warning_for_range_not_found(self, range_status_consumer_factory, websocket_scope_range_status):
        """connect() logs warning when range not found."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with (
            patch("cms.get_range", side_effect=CMSError("Not found")),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer.connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "42" in call_args or "not found" in call_args.lower()

    async def test_sets_range_id_from_url_route(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() sets range_id from URL route kwargs."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        assert consumer.range_id == 42

    async def test_sets_group_name_for_range(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() sets group_name for range status updates."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        assert consumer.group_name == "range_status_42"


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectChannelGroup:
    """Tests for RangeStatusConsumer.connect channel group handling."""

    # -------------------------------------------------------------------------
    # Channel group - joining for updates
    # -------------------------------------------------------------------------

    async def test_joins_channel_group_for_range(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance, mock_channel_layer
    ):
        """connect() joins the channel group for range status updates."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        mock_channel_layer.group_add.assert_awaited_once_with("range_status_42", "test-channel")

    async def test_does_not_join_group_on_auth_failure(
        self, range_status_consumer_factory, anonymous_user, mock_channel_layer
    ):
        """connect() does not join group when authentication fails."""
        scope = {
            "type": "websocket",
            "user": anonymous_user,
            "url_route": {"kwargs": {"range_id": "42"}},
        }
        consumer = range_status_consumer_factory(scope)

        await consumer.connect()

        mock_channel_layer.group_add.assert_not_awaited()


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectAccept:
    """Tests for RangeStatusConsumer.connect WebSocket acceptance."""

    # -------------------------------------------------------------------------
    # WebSocket acceptance
    # -------------------------------------------------------------------------

    async def test_accepts_websocket_on_success(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() accepts WebSocket connection on success."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        consumer.accept.assert_awaited_once()

    async def test_does_not_accept_on_auth_failure(self, range_status_consumer_factory, anonymous_user):
        """connect() does not accept WebSocket when authentication fails."""
        scope = {
            "type": "websocket",
            "user": anonymous_user,
            "url_route": {"kwargs": {"range_id": "42"}},
        }
        consumer = range_status_consumer_factory(scope)

        await consumer.connect()

        consumer.accept.assert_not_awaited()

    async def test_does_not_accept_on_range_not_found(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """connect() does not accept WebSocket when range not found."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", side_effect=CMSError("Not found")):
            await consumer.connect()

        consumer.accept.assert_not_awaited()


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectHydration:
    """Tests for RangeStatusConsumer.connect status hydration."""

    # -------------------------------------------------------------------------
    # Status hydration - initial state
    # -------------------------------------------------------------------------

    async def test_sends_initial_status_on_connect(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() sends initial status message on successful connection."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        consumer.send.assert_awaited_once()
        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "status"
        assert message["range_id"] == 42
        assert message["status"] == RangeStatus.READY.value

    async def test_hydration_message_contains_type_field(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() hydration message contains type='status'."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "status"

    async def test_hydration_message_contains_range_id(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() hydration message contains range_id."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["range_id"] == 42

    async def test_hydration_message_contains_status(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() hydration message contains current status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with patch("cms.get_range", return_value=mock_range_instance):
            await consumer.connect()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert "status" in message


@pytest.mark.asyncio
class TestRangeStatusConsumerConnectLogging:
    """Tests for RangeStatusConsumer.connect logging."""

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    async def test_logs_info_on_successful_connect(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_range_instance
    ):
        """connect() logs INFO on successful connection."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)

        with (
            patch("cms.get_range", return_value=mock_range_instance),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer.connect()

        mock_logger.info.assert_called()
        call_args = str(mock_logger.info.call_args)
        assert "42" in call_args or "connected" in call_args.lower()
