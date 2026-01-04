"""Tests for SSHConsumer.receive.

Tests the WebSocket message handler that forwards input to SSH.

Contract being tested:
- Inputs: text_data (JSON string) or bytes_data
- Outputs: None
- Side effects:
  - For "input" type: sends data to SSH as bytes
  - For "resize" type: calls SSH resize with cols/rows
- Errors: Logs warnings for invalid JSON, exceptions for other errors
- Logging: Logs warning on invalid JSON, exception on other errors
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestSSHConsumerReceiveInput:
    """Tests for SSHConsumer.receive handling input messages."""

    # -------------------------------------------------------------------------
    # Input messages
    # -------------------------------------------------------------------------

    async def test_sends_input_data_to_ssh(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() sends input data to SSH connection."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "input", "data": "ls -la\n"})
        await consumer.receive(text_data=message)

        mock_ssh.send.assert_awaited_once()
        call_args = mock_ssh.send.call_args
        assert call_args[0][0] == b"ls -la\n"

    async def test_encodes_input_data_as_utf8(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() encodes input data as UTF-8 bytes."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        # Message with special characters
        message = json.dumps({"type": "input", "data": "éclaté\n"})
        await consumer.receive(text_data=message)

        call_args = mock_ssh.send.call_args
        assert call_args[0][0] == "éclaté\n".encode()

    async def test_handles_empty_input_data(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() handles empty input data."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "input", "data": ""})
        await consumer.receive(text_data=message)

        mock_ssh.send.assert_awaited_once()
        call_args = mock_ssh.send.call_args
        assert call_args[0][0] == b""

    async def test_handles_missing_data_field(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() handles missing data field in input message."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "input"})
        await consumer.receive(text_data=message)

        # Should send empty bytes
        mock_ssh.send.assert_awaited_once()
        call_args = mock_ssh.send.call_args
        assert call_args[0][0] == b""


@pytest.mark.asyncio
class TestSSHConsumerReceiveResize:
    """Tests for SSHConsumer.receive handling resize messages."""

    # -------------------------------------------------------------------------
    # Resize messages
    # -------------------------------------------------------------------------

    async def test_calls_ssh_resize_with_cols_and_rows(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() calls SSH resize with cols and rows."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "resize", "cols": 120, "rows": 40})
        await consumer.receive(text_data=message)

        mock_ssh.resize.assert_awaited_once_with(120, 40)

    async def test_uses_default_cols_when_missing(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() uses default cols (80) when not provided."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "resize", "rows": 40})
        await consumer.receive(text_data=message)

        mock_ssh.resize.assert_awaited_once_with(80, 40)

    async def test_uses_default_rows_when_missing(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() uses default rows (24) when not provided."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "resize", "cols": 120})
        await consumer.receive(text_data=message)

        mock_ssh.resize.assert_awaited_once_with(120, 24)

    async def test_uses_default_cols_and_rows_when_both_missing(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """receive() uses default cols/rows (80/24) when not provided."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "resize"})
        await consumer.receive(text_data=message)

        mock_ssh.resize.assert_awaited_once_with(80, 24)


@pytest.mark.asyncio
class TestSSHConsumerReceiveNoConnection:
    """Tests for SSHConsumer.receive when no SSH connection."""

    # -------------------------------------------------------------------------
    # No SSH connection
    # -------------------------------------------------------------------------

    async def test_does_nothing_when_no_ssh_connection(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() does nothing when ssh_conn is None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer.ssh_conn = None

        message = json.dumps({"type": "input", "data": "test"})

        # Should not raise
        await consumer.receive(text_data=message)

    async def test_does_nothing_when_no_text_data(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() does nothing when text_data is None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        # Should not raise or call anything
        await consumer.receive(text_data=None)

        mock_ssh.send.assert_not_awaited()
        mock_ssh.resize.assert_not_awaited()


@pytest.mark.asyncio
class TestSSHConsumerReceiveInvalidJSON:
    """Tests for SSHConsumer.receive handling invalid JSON."""

    # -------------------------------------------------------------------------
    # Invalid JSON handling
    # -------------------------------------------------------------------------

    async def test_logs_warning_on_invalid_json(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() logs warning when text_data is not valid JSON."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.receive(text_data="not valid json")

        mock_logger.warning.assert_called_once()
        call_args = str(mock_logger.warning.call_args)
        assert "Invalid JSON" in call_args or "test-uuid" in call_args

    async def test_does_not_raise_on_invalid_json(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() does not raise exception on invalid JSON."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        # Should not raise
        await consumer.receive(text_data="not valid json")


@pytest.mark.asyncio
class TestSSHConsumerReceiveUnknownType:
    """Tests for SSHConsumer.receive handling unknown message types."""

    # -------------------------------------------------------------------------
    # Unknown message types
    # -------------------------------------------------------------------------

    async def test_ignores_unknown_message_type(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() ignores messages with unknown type."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"type": "unknown", "data": "test"})
        await consumer.receive(text_data=message)

        # Should not call any SSH methods
        mock_ssh.send.assert_not_awaited()
        mock_ssh.resize.assert_not_awaited()

    async def test_ignores_message_without_type(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() ignores messages without type field."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        message = json.dumps({"data": "test"})
        await consumer.receive(text_data=message)

        # Should not call any SSH methods
        mock_ssh.send.assert_not_awaited()
        mock_ssh.resize.assert_not_awaited()


@pytest.mark.asyncio
class TestSSHConsumerReceiveErrorHandling:
    """Tests for SSHConsumer.receive error handling."""

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    async def test_logs_exception_on_send_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() logs exception when SSH send fails."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.send = AsyncMock(side_effect=RuntimeError("Send failed"))
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            message = json.dumps({"type": "input", "data": "test"})
            await consumer.receive(text_data=message)

        mock_logger.exception.assert_called_once()
        call_args = str(mock_logger.exception.call_args)
        assert "test-uuid" in call_args or "terminal" in call_args.lower()

    async def test_logs_exception_on_resize_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() logs exception when SSH resize fails."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.resize = AsyncMock(side_effect=RuntimeError("Resize failed"))
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            message = json.dumps({"type": "resize", "cols": 120, "rows": 40})
            await consumer.receive(text_data=message)

        mock_logger.exception.assert_called_once()

    async def test_does_not_propagate_send_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() catches send errors without propagating."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.send = AsyncMock(side_effect=RuntimeError("Send failed"))
        consumer.ssh_conn = mock_ssh

        # Should not raise
        message = json.dumps({"type": "input", "data": "test"})
        await consumer.receive(text_data=message)

    async def test_does_not_propagate_resize_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() catches resize errors without propagating."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.resize = AsyncMock(side_effect=RuntimeError("Resize failed"))
        consumer.ssh_conn = mock_ssh

        # Should not raise
        message = json.dumps({"type": "resize", "cols": 120, "rows": 40})
        await consumer.receive(text_data=message)


@pytest.mark.asyncio
class TestSSHConsumerReceiveBytesData:
    """Tests for SSHConsumer.receive handling bytes_data."""

    # -------------------------------------------------------------------------
    # Bytes data handling
    # -------------------------------------------------------------------------

    async def test_ignores_bytes_data(self, ssh_consumer_factory, websocket_scope_authenticated):
        """receive() ignores bytes_data parameter."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        # Should not process bytes_data
        await consumer.receive(bytes_data=b"binary data")

        mock_ssh.send.assert_not_awaited()
        mock_ssh.resize.assert_not_awaited()
