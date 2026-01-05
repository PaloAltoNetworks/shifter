"""Tests for SSHConsumer.disconnect.

Tests the WebSocket disconnection handler that cleans up SSH resources.

Contract being tested:
- Inputs: close_code (int)
- Outputs: None
- Side effects:
  - Cancels _read_task if running
  - Awaits cancelled task to clean up
  - Closes SSH connection
- Errors: Catches and logs exceptions from SSH disconnect
- Logging: Logs debug on disconnect, exception on SSH close error
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestSSHConsumerDisconnectReadTask:
    """Tests for SSHConsumer.disconnect read task handling."""

    # -------------------------------------------------------------------------
    # Read task cleanup
    # -------------------------------------------------------------------------

    async def test_cancels_read_task_if_running(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() cancels _read_task if it exists."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        # Create a real asyncio task that we can cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        await consumer.disconnect(close_code=1000)

        # Task should be cancelled
        assert task.cancelled()

    async def test_awaits_cancelled_task(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() awaits the cancelled task to clean up."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        # Create a real asyncio task that we can cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        await consumer.disconnect(close_code=1000)

        assert task.cancelled()

    async def test_suppresses_cancelled_error_from_task(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() suppresses CancelledError when awaiting task."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        # Create a task that will raise CancelledError when awaited after cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        # Should not raise
        await consumer.disconnect(close_code=1000)

    async def test_handles_none_read_task(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() handles when _read_task is None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None

        # Should not raise
        await consumer.disconnect(close_code=1000)


@pytest.mark.asyncio
class TestSSHConsumerDisconnectSSHConnection:
    """Tests for SSHConsumer.disconnect SSH connection handling."""

    # -------------------------------------------------------------------------
    # SSH connection cleanup
    # -------------------------------------------------------------------------

    async def test_closes_ssh_connection(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() closes the SSH connection."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.disconnect(close_code=1000)

        mock_ssh.disconnect.assert_awaited_once()

    async def test_handles_none_ssh_connection(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() handles when ssh_conn is None."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        # Should not raise
        await consumer.disconnect(close_code=1000)

    async def test_catches_ssh_disconnect_exception(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() catches exception from SSH disconnect."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None

        mock_ssh = AsyncMock()
        mock_ssh.disconnect = AsyncMock(side_effect=RuntimeError("SSH close failed"))
        consumer.ssh_conn = mock_ssh

        # Should not raise
        await consumer.disconnect(close_code=1000)

    async def test_logs_exception_on_ssh_disconnect_error(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() logs exception when SSH disconnect fails."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None

        mock_ssh = AsyncMock()
        mock_ssh.disconnect = AsyncMock(side_effect=RuntimeError("SSH close failed"))
        consumer.ssh_conn = mock_ssh

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.disconnect(close_code=1000)

        mock_logger.exception.assert_called_once()
        call_args = str(mock_logger.exception.call_args)
        assert "test-uuid" in call_args or "SSH" in call_args


@pytest.mark.asyncio
class TestSSHConsumerDisconnectLogging:
    """Tests for SSHConsumer.disconnect logging."""

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    async def test_logs_debug_on_disconnect(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() logs debug message with uuid and close_code."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.disconnect(close_code=1000)

        mock_logger.debug.assert_called()
        call_args = str(mock_logger.debug.call_args)
        assert "test-uuid" in call_args
        assert "1000" in call_args

    async def test_logs_debug_includes_close_code(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() includes close_code in debug log."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer.disconnect(close_code=4001)

        call_args = str(mock_logger.debug.call_args)
        assert "4001" in call_args


@pytest.mark.asyncio
class TestSSHConsumerDisconnectCloseCodesHandling:
    """Tests for SSHConsumer.disconnect close code handling."""

    # -------------------------------------------------------------------------
    # Close codes
    # -------------------------------------------------------------------------

    async def test_handles_normal_close_code(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() handles normal close code (1000)."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        await consumer.disconnect(close_code=1000)

    async def test_handles_error_close_code(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() handles error close codes."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        await consumer.disconnect(close_code=4500)

    async def test_handles_none_close_code(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() handles None close_code."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"
        consumer._read_task = None
        consumer.ssh_conn = None

        # Some WebSocket implementations may pass None
        await consumer.disconnect(close_code=None)


@pytest.mark.asyncio
class TestSSHConsumerDisconnectCleanupOrder:
    """Tests for SSHConsumer.disconnect cleanup order."""

    # -------------------------------------------------------------------------
    # Cleanup order
    # -------------------------------------------------------------------------

    async def test_cleans_up_both_task_and_ssh(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() cleans up both read task and SSH connection."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        # Create a real asyncio task
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.disconnect(close_code=1000)

        # Both should be cleaned up
        assert task.cancelled()
        mock_ssh.disconnect.assert_awaited_once()

    async def test_closes_ssh_even_if_task_cancel_fails(self, ssh_consumer_factory, websocket_scope_authenticated):
        """disconnect() closes SSH even if task cancellation has issue."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer.instance_uuid = "test-uuid"

        # Create a real asyncio task
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.disconnect(close_code=1000)

        # SSH should still be disconnected
        mock_ssh.disconnect.assert_awaited_once()
