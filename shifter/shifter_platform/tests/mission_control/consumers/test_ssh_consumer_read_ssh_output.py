"""Tests for SSHConsumer._read_ssh_output.

Tests the background task that reads SSH output and sends it to the WebSocket.

Contract being tested:
- Inputs: None (reads from self.ssh_conn.receive())
- Outputs: Sends JSON messages to WebSocket with {type: "output", data: ...}
- Side effects:
  - Loops reading SSH output until None received or error
  - Sends output data as JSON to WebSocket
  - Closes WebSocket when SSH read returns None or on error
- Errors: Catches CancelledError silently, logs other exceptions
- Logging: Logs exception on error reading SSH output
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestSSHConsumerReadSSHOutputHappyPath:
    """Tests for SSHConsumer._read_ssh_output success path."""

    # -------------------------------------------------------------------------
    # Happy path - data flow
    # -------------------------------------------------------------------------

    async def test_sends_output_message_when_data_received(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() sends output message when SSH data received."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # Return data once, then None to exit the loop
        mock_ssh.receive = AsyncMock(side_effect=[b"Hello World", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        # Should have sent one message
        consumer.send.assert_awaited()
        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "output"
        assert message["data"] == "Hello World"

    async def test_sends_multiple_output_messages(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() sends multiple messages for multiple data chunks."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"First", b"Second", b"Third", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        # Should have sent three messages
        assert consumer.send.await_count == 3

    async def test_decodes_bytes_as_utf8(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() decodes bytes as UTF-8."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # UTF-8 encoded string with special characters
        mock_ssh.receive = AsyncMock(side_effect=[b"\xc3\xa9\xc3\xa0\xc3\xbc", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["data"] == "éàü"

    async def test_replaces_invalid_utf8_sequences(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() replaces invalid UTF-8 with replacement character."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # Invalid UTF-8 sequence
        mock_ssh.receive = AsyncMock(side_effect=[b"Hello\xff\xfeWorld", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        # Invalid bytes should be replaced with replacement character
        assert "Hello" in message["data"]
        assert "World" in message["data"]


@pytest.mark.asyncio
class TestSSHConsumerReadSSHOutputLoopTermination:
    """Tests for SSHConsumer._read_ssh_output loop termination."""

    # -------------------------------------------------------------------------
    # Loop termination - various exit conditions
    # -------------------------------------------------------------------------

    async def test_exits_loop_when_receive_returns_none(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() exits loop when SSH receive returns None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(return_value=None)
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        # Should have called receive once and exited
        mock_ssh.receive.assert_awaited_once()

    async def test_exits_loop_when_receive_returns_empty_bytes(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """_read_ssh_output() exits loop when SSH receive returns empty bytes."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(return_value=b"")
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        # Empty bytes should also exit the loop (falsy value)
        mock_ssh.receive.assert_awaited_once()

    async def test_closes_websocket_after_loop_exit(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() closes WebSocket after loop exits."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(return_value=None)
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()


@pytest.mark.asyncio
class TestSSHConsumerReadSSHOutputErrorHandling:
    """Tests for SSHConsumer._read_ssh_output error handling."""

    # -------------------------------------------------------------------------
    # Error handling - exception cases
    # -------------------------------------------------------------------------

    async def test_handles_cancelled_error_silently(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() handles CancelledError silently."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=asyncio.CancelledError())
        consumer.ssh_conn = mock_ssh

        # Should not raise
        await consumer._read_ssh_output()

        # Should still close WebSocket
        consumer.close.assert_awaited_once()

    async def test_does_not_log_cancelled_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() does not log CancelledError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=asyncio.CancelledError())
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer._read_ssh_output()

        mock_logger.exception.assert_not_called()

    async def test_logs_exception_on_read_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() logs exception on read error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=RuntimeError("Read failed"))
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer._read_ssh_output()

        mock_logger.exception.assert_called_once()
        call_args = str(mock_logger.exception.call_args)
        assert "test-uuid" in call_args or "SSH" in call_args

    async def test_closes_websocket_on_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() closes WebSocket on error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=RuntimeError("Read failed"))
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    async def test_handles_connection_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() handles ConnectionError gracefully."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=ConnectionError("Lost connection"))
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer._read_ssh_output()

        mock_logger.exception.assert_called_once()
        consumer.close.assert_awaited_once()


@pytest.mark.asyncio
class TestSSHConsumerReadSSHOutputJSONFormat:
    """Tests for SSHConsumer._read_ssh_output JSON message format."""

    # -------------------------------------------------------------------------
    # JSON format - message structure
    # -------------------------------------------------------------------------

    async def test_sends_json_with_type_output(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() sends JSON with type='output'."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"test", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "output"

    async def test_sends_json_with_data_field(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() sends JSON with data field containing output."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"terminal output", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert "data" in message
        assert message["data"] == "terminal output"

    async def test_sends_valid_json_string(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() sends valid JSON string via text_data."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"test", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        # Should be able to parse the text_data as JSON without error
        text_data = call_args[1]["text_data"]
        parsed = json.loads(text_data)
        assert isinstance(parsed, dict)


@pytest.mark.asyncio
class TestSSHConsumerReadSSHOutputEdgeCases:
    """Tests for SSHConsumer._read_ssh_output edge cases."""

    # -------------------------------------------------------------------------
    # Edge cases - various boundary conditions
    # -------------------------------------------------------------------------

    async def test_handles_large_data_chunk(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() handles large data chunks."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        large_data = b"x" * 100000  # 100KB
        mock_ssh.receive = AsyncMock(side_effect=[large_data, None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert len(message["data"]) == 100000

    async def test_handles_special_json_characters(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() properly escapes special JSON characters."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # Data with special JSON characters
        mock_ssh.receive = AsyncMock(side_effect=[b'{"key": "value"}\n\t\\', None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        # Should be able to parse without error
        message = json.loads(call_args[1]["text_data"])
        assert '{"key": "value"}' in message["data"]

    async def test_handles_newlines_in_output(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() handles newlines in terminal output."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"line1\nline2\r\nline3", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["data"] == "line1\nline2\r\nline3"

    async def test_handles_binary_control_sequences(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() handles ANSI control sequences."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # ANSI escape sequence for red text
        mock_ssh.receive = AsyncMock(side_effect=[b"\x1b[31mRed Text\x1b[0m", None])
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["data"] == "\x1b[31mRed Text\x1b[0m"

    async def test_skips_sending_when_no_data(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_read_ssh_output() doesn't send when data is empty/None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        mock_ssh = AsyncMock()
        # Return None immediately
        mock_ssh.receive = AsyncMock(return_value=None)
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        # Should not have sent any messages
        consumer.send.assert_not_awaited()
