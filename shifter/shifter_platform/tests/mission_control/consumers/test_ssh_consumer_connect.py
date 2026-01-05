"""Tests for SSHConsumer.connect.

Tests the WebSocket connection handler that orchestrates the
connection flow, calling _do_connect and handling exceptions.

Contract being tested:
- Inputs: WebSocket connection request (implicit via scope)
- Outputs: None (async method)
- Side effects: Calls _do_connect, closes with SERVER_ERROR on exception
- Errors: Catches all exceptions and closes connection
- Logging: Logs exception on unexpected error
"""

from unittest.mock import AsyncMock, patch

import pytest

from shared.enums import WebSocketCloseCode


@pytest.mark.asyncio
class TestSSHConsumerConnect:
    """Tests for SSHConsumer.connect."""

    # -------------------------------------------------------------------------
    # Happy path - connection succeeds
    # -------------------------------------------------------------------------

    async def test_calls_do_connect_on_connection(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() calls _do_connect to handle the connection flow."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock()

        await consumer.connect()

        consumer._do_connect.assert_awaited_once()

    async def test_does_not_close_on_successful_connect(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() does not close connection when _do_connect succeeds."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock()

        await consumer.connect()

        consumer.close.assert_not_awaited()

    # -------------------------------------------------------------------------
    # Error handling - exception in _do_connect
    # -------------------------------------------------------------------------

    async def test_closes_with_server_error_on_unexpected_exception(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """connect() closes with SERVER_ERROR when _do_connect raises unexpected exception."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=RuntimeError("Unexpected"))

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    async def test_closes_with_server_error_on_value_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() closes with SERVER_ERROR when _do_connect raises ValueError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=ValueError("Invalid data"))

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    async def test_closes_with_server_error_on_type_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() closes with SERVER_ERROR when _do_connect raises TypeError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=TypeError("Type error"))

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    async def test_closes_with_server_error_on_attribute_error(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """connect() closes with SERVER_ERROR when _do_connect raises AttributeError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=AttributeError("Missing attr"))

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    async def test_closes_with_server_error_on_key_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() closes with SERVER_ERROR when _do_connect raises KeyError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=KeyError("Missing key"))

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    # -------------------------------------------------------------------------
    # Logging - error is logged on exception
    # Note: We mock the logger to verify logging behavior, as mission_control
    # logger has propagate=False which prevents caplog capture
    # -------------------------------------------------------------------------

    async def test_logs_exception_on_unexpected_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() calls logger.exception when _do_connect raises unexpected error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.connect()

        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args
        assert "Unexpected error in WebSocket connect" in call_args[0][0]

    async def test_logs_exception_with_exc_info(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() logs exception with exc_info via logger.exception."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=RuntimeError("Test error"))

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.connect()

        # logger.exception automatically includes exc_info
        mock_logger.exception.assert_called_once()

    async def test_logs_only_once_per_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() logs exception exactly once per error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=ValueError("Detailed error"))

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.connect()

        # Should only log once (via exception method)
        assert mock_logger.exception.call_count == 1

    # -------------------------------------------------------------------------
    # Exception handling does not re-raise
    # -------------------------------------------------------------------------

    async def test_does_not_propagate_exception(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() catches exceptions and does not propagate them."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=RuntimeError("Should be caught"))

        # Should not raise - exception should be caught
        await consumer.connect()

        # If we get here, the exception was caught
        assert True

    async def test_does_not_propagate_base_exception(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() catches Exception subclasses (but not BaseException)."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        # Generic Exception (not KeyboardInterrupt/SystemExit which are BaseException)
        consumer._do_connect = AsyncMock(side_effect=Exception("Generic exception"))

        # Should not raise
        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVER_ERROR)

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    async def test_handles_none_returned_from_do_connect(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() handles when _do_connect returns None (normal case)."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(return_value=None)

        await consumer.connect()

        # Should complete without error
        consumer._do_connect.assert_awaited_once()
        consumer.close.assert_not_awaited()

    async def test_handles_async_cancellation_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """connect() handles asyncio.CancelledError appropriately."""
        import asyncio

        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._do_connect = AsyncMock(side_effect=asyncio.CancelledError())

        # CancelledError is a BaseException, so it should propagate or be handled
        # depending on Python version. In Python 3.8+, it's an Exception subclass
        # but is typically re-raised in async code
        with pytest.raises(asyncio.CancelledError):
            await consumer.connect()
