"""Tests for RangeStatusConsumer.disconnect.

Tests the WebSocket disconnection handler that leaves the channel group.

Contract being tested:
- Inputs: close_code (int)
- Outputs: None
- Side effects: Leaves channel group if group_name is set
- Errors: None
- Logging: Logs info on disconnect with range_id and close_code
"""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
class TestRangeStatusConsumerDisconnectChannelGroup:
    """Tests for RangeStatusConsumer.disconnect channel group handling."""

    # -------------------------------------------------------------------------
    # Channel group - leaving on disconnect
    # -------------------------------------------------------------------------

    async def test_leaves_channel_group_on_disconnect(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() leaves the channel group."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        await consumer.disconnect(close_code=1000)

        mock_channel_layer.group_discard.assert_awaited_once_with("range_status_42", "test-channel")

    async def test_does_not_leave_group_when_group_name_is_none(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() does not leave group when group_name is None."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = None

        await consumer.disconnect(close_code=1000)

        mock_channel_layer.group_discard.assert_not_awaited()


@pytest.mark.asyncio
class TestRangeStatusConsumerDisconnectLogging:
    """Tests for RangeStatusConsumer.disconnect logging."""

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    async def test_logs_info_on_disconnect(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() logs INFO with range_id and close_code."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.disconnect(close_code=1000)

        mock_logger.info.assert_called()
        call_args = str(mock_logger.info.call_args)
        assert "42" in call_args
        assert "1000" in call_args

    async def test_logs_info_with_different_close_code(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() logs INFO with the actual close code."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.disconnect(close_code=4001)

        call_args = str(mock_logger.info.call_args)
        assert "4001" in call_args


@pytest.mark.asyncio
class TestRangeStatusConsumerDisconnectCloseCodes:
    """Tests for RangeStatusConsumer.disconnect close code handling."""

    # -------------------------------------------------------------------------
    # Close codes
    # -------------------------------------------------------------------------

    async def test_handles_normal_close_code(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() handles normal close code (1000)."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        await consumer.disconnect(close_code=1000)

        mock_channel_layer.group_discard.assert_awaited_once()

    async def test_handles_error_close_code(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() handles error close codes."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        await consumer.disconnect(close_code=4500)

        mock_channel_layer.group_discard.assert_awaited_once()

    async def test_handles_none_close_code(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() handles None close_code."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        await consumer.disconnect(close_code=None)

        mock_channel_layer.group_discard.assert_awaited_once()


@pytest.mark.asyncio
class TestRangeStatusConsumerDisconnectEdgeCases:
    """Tests for RangeStatusConsumer.disconnect edge cases."""

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    async def test_handles_disconnect_without_connect(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() handles being called without successful connect."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        # range_id and group_name are still None (connect not called)

        # Should not raise
        await consumer.disconnect(close_code=1000)

    async def test_handles_disconnect_with_only_range_id_set(
        self, range_status_consumer_factory, websocket_scope_range_status, mock_channel_layer
    ):
        """disconnect() handles when range_id is set but group_name is None."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = None

        # Should not raise or try to leave group
        await consumer.disconnect(close_code=1000)

        mock_channel_layer.group_discard.assert_not_awaited()
