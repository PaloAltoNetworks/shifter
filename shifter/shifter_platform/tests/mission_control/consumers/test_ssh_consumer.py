"""Tests for SSHConsumer.

Integration-style tests covering the WebSocket consumer lifecycle:
connect, receive input, send output, disconnect.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser

from shared.enums import WebSocketCloseCode


@pytest.fixture
def consumer():
    """Create an SSHConsumer with mocked WebSocket methods."""
    from mission_control.consumers import SSHConsumer

    c = SSHConsumer()
    c.channel_name = "test-channel"
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
        "url_route": {"kwargs": {"instance_uuid": "test-uuid-1234"}},
    }


@pytest.fixture
def unauthenticated_scope():
    """WebSocket scope with anonymous user."""
    return {
        "type": "websocket",
        "user": AnonymousUser(),
        "url_route": {"kwargs": {"instance_uuid": "test-uuid-1234"}},
    }


class TestSSHConsumerConnect:
    """Tests for connect() and _do_connect() behavior."""

    @pytest.mark.asyncio
    async def test_rejects_unauthenticated_user(self, consumer, unauthenticated_scope):
        """Unauthenticated users are rejected."""
        consumer.scope = unauthenticated_scope

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    @pytest.mark.asyncio
    async def test_rejects_missing_instance_uuid(self, consumer):
        """Missing instance_uuid returns INVALID_REQUEST."""
        user = MagicMock(is_authenticated=True)
        consumer.scope = {
            "type": "websocket",
            "user": user,
            "url_route": {"kwargs": {}},
        }

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)

    @pytest.mark.asyncio
    async def test_rejects_on_value_error(self, consumer, authenticated_scope):
        """ValueError from connect_terminal returns NOT_FOUND.

        Engine raises ValueError for: no active range, range not ready,
        instance not in range, etc.
        """
        consumer.scope = authenticated_scope

        with patch("engine.services.connect_terminal", side_effect=ValueError("Instance not found")):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    @pytest.mark.asyncio
    async def test_rejects_on_permission_error(self, consumer, authenticated_scope):
        """PermissionError from connect_terminal returns PERMISSION_DENIED."""
        consumer.scope = authenticated_scope

        with patch("engine.services.connect_terminal", side_effect=PermissionError("Not authorized")):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.PERMISSION_DENIED)

    @pytest.mark.asyncio
    async def test_rejects_on_ssh_connection_failure(self, consumer, authenticated_scope):
        """SSH connection failure returns SSH_CONNECTION_FAILED."""
        consumer.scope = authenticated_scope
        mock_ssh = AsyncMock()
        mock_ssh.connect.side_effect = ConnectionError("SSH failed")

        with patch("engine.services.connect_terminal", return_value=mock_ssh):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)

    @pytest.mark.asyncio
    async def test_accepts_on_successful_connect(self, consumer, authenticated_scope):
        """Successful connection accepts WebSocket and starts read task."""
        consumer.scope = authenticated_scope
        mock_ssh = AsyncMock()

        with (
            patch("engine.services.connect_terminal", return_value=mock_ssh),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_create_task.return_value = MagicMock()
            await consumer.connect()

        consumer.accept.assert_awaited_once()
        mock_ssh.connect.assert_awaited_once()
        mock_create_task.assert_called_once()


class TestSSHConsumerDisconnect:
    """Tests for disconnect() behavior."""

    @pytest.mark.asyncio
    async def test_cancels_read_task(self, consumer):
        """Disconnect cancels the background read task."""

        # Create a real task that we can cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        await consumer.disconnect(close_code=1000)

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_closes_ssh_connection(self, consumer):
        """Disconnect closes the SSH connection."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.disconnect(close_code=1000)

        mock_ssh.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_disconnect_without_connect(self, consumer):
        """Disconnect handles case where connect never completed."""
        consumer.ssh_conn = None
        consumer._read_task = None

        await consumer.disconnect(close_code=1000)
        # Should not raise


class TestSSHConsumerReceive:
    """Tests for receive() input handling."""

    @pytest.mark.asyncio
    async def test_forwards_input_to_ssh(self, consumer):
        """Input messages are forwarded to SSH connection."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.receive(text_data=json.dumps({"type": "input", "data": "ls -la\n"}))

        mock_ssh.send.assert_awaited_once_with(b"ls -la\n")

    @pytest.mark.asyncio
    async def test_handles_resize_message(self, consumer):
        """Resize messages update terminal dimensions."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.receive(text_data=json.dumps({"type": "resize", "cols": 120, "rows": 40}))

        mock_ssh.resize.assert_awaited_once_with(120, 40)

    @pytest.mark.asyncio
    async def test_ignores_invalid_json(self, consumer):
        """Invalid JSON is ignored (logged as warning)."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer.receive(text_data="not json")

        mock_ssh.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ignores_when_no_ssh_connection(self, consumer):
        """Messages before SSH connection is established are ignored."""
        consumer.ssh_conn = None

        await consumer.receive(text_data=json.dumps({"type": "input", "data": "test"}))
        # Should not raise


class TestSSHConsumerReadOutput:
    """Tests for _read_ssh_output() background task."""

    @pytest.mark.asyncio
    async def test_sends_output_to_websocket(self, consumer):
        """SSH output is sent to WebSocket as JSON."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive = AsyncMock(side_effect=[b"Hello World", None])
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        # Mock is_connected to return False after first iteration
        call_count = [0]

        def is_connected_side_effect():
            call_count[0] += 1
            return call_count[0] <= 1

        type(mock_ssh).is_connected = property(lambda self: is_connected_side_effect())

        await consumer._read_ssh_output()

        consumer.send.assert_awaited()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["type"] == "output"
        assert message["data"] == "Hello World"

    @pytest.mark.asyncio
    async def test_handles_cancelled_error_silently(self, consumer):
        """CancelledError (from task cancellation) is handled silently."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive.side_effect = asyncio.CancelledError()
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_closes_websocket_on_error(self, consumer):
        """Other errors close the WebSocket."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive.side_effect = RuntimeError("Read failed")
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()
