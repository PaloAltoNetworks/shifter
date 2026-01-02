"""Tests for SSHConnection.receive."""

import logging
from unittest.mock import AsyncMock, patch

import asyncssh
import pytest

from engine.ssh import SSHConnection, SSHConnectionError


class TestSSHConnectionReceive:
    """Tests for SSHConnection.receive method."""

    # -------------------------------------------------------------------------
    # Happy path - receive succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reads_data_from_stdout(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive reads data from the process stdout."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        expected_data = b"command output\n"
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=expected_data)

        result = await conn.receive()

        assert result == expected_data

    @pytest.mark.asyncio
    async def test_reads_up_to_4096_bytes(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive requests up to 4096 bytes from stdout."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=b"data")

        await conn.receive()

        mock_asyncssh_process.stdout.read.assert_called_once_with(4096)

    @pytest.mark.asyncio
    async def test_uses_default_timeout(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive uses default timeout of 0.1 seconds."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.return_value = b"data"

            await conn.receive()

            mock_wait_for.assert_called_once()
            call_args = mock_wait_for.call_args
            assert call_args[1]["timeout"] == 0.1

    @pytest.mark.asyncio
    async def test_uses_custom_timeout(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive uses custom timeout when specified."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.return_value = b"data"

            await conn.receive(timeout=5.0)

            mock_wait_for.assert_called_once()
            call_args = mock_wait_for.call_args
            assert call_args[1]["timeout"] == 5.0

    @pytest.mark.asyncio
    async def test_returns_empty_bytes_when_no_data(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive returns empty bytes when stdout returns None/empty."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=None)

        result = await conn.receive()

        assert result == b""

    @pytest.mark.asyncio
    async def test_returns_empty_bytes_when_stdout_empty(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive returns empty bytes when stdout returns empty bytes."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=b"")

        result = await conn.receive()

        assert result == b""

    # -------------------------------------------------------------------------
    # Error handling - not connected
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_error_when_not_connected(self, valid_connection_params):
        """Receive raises SSHConnectionError when not connected."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = None

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.receive()

    @pytest.mark.asyncio
    async def test_raises_error_when_process_is_none(self, valid_connection_params, mock_asyncssh_connection):
        """Receive raises SSHConnectionError when process is None."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = None

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.receive()

    # -------------------------------------------------------------------------
    # Error handling - timeout
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_empty_bytes_on_timeout(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive returns empty bytes when timeout occurs."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = TimeoutError()

            result = await conn.receive()

            assert result == b""

    @pytest.mark.asyncio
    async def test_returns_empty_bytes_on_asyncio_timeout_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive returns empty bytes when asyncio.TimeoutError occurs."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = TimeoutError()

            result = await conn.receive()

            assert result == b""

    # -------------------------------------------------------------------------
    # Error handling - break received
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_empty_bytes_on_break_received(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive returns empty bytes when BreakReceived occurs."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = asyncssh.BreakReceived(0)

            result = await conn.receive()

            assert result == b""

    # -------------------------------------------------------------------------
    # Boundary conditions - various data types
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_receives_binary_data(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive can receive arbitrary binary data."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        expected_data = bytes(range(256))
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=expected_data)

        result = await conn.receive()

        assert result == expected_data

    @pytest.mark.asyncio
    async def test_receives_control_characters(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive can receive control characters."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        expected_data = b"\x1b[H\x1b[2J"  # Clear screen sequence
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=expected_data)

        result = await conn.receive()

        assert result == expected_data

    @pytest.mark.asyncio
    async def test_receives_large_data(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive can receive large amounts of data up to buffer size."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        expected_data = b"x" * 4096
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=expected_data)

        result = await conn.receive()

        assert result == expected_data

    @pytest.mark.asyncio
    async def test_receives_utf8_text(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive can receive UTF-8 encoded text."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        expected_data = "héllo wörld 日本語".encode()
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=expected_data)

        result = await conn.receive()

        assert result == expected_data

    # -------------------------------------------------------------------------
    # Multiple receives
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_can_receive_multiple_times(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive can be called multiple times."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(side_effect=[b"first", b"second", b"third"])

        result1 = await conn.receive()
        result2 = await conn.receive()
        result3 = await conn.receive()

        assert result1 == b"first"
        assert result2 == b"second"
        assert result3 == b"third"

    @pytest.mark.asyncio
    async def test_handles_interleaved_data_and_timeouts(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive handles interleaved data and timeouts."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = [b"data", TimeoutError(), b"more data"]

            result1 = await conn.receive()
            result2 = await conn.receive()
            result3 = await conn.receive()

            assert result1 == b"data"
            assert result2 == b""
            assert result3 == b"more data"

    # -------------------------------------------------------------------------
    # Timeout values
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_accepts_zero_timeout(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Receive accepts zero timeout."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.return_value = b"data"

            await conn.receive(timeout=0)

            call_args = mock_wait_for.call_args
            assert call_args[1]["timeout"] == 0

    @pytest.mark.asyncio
    async def test_accepts_large_timeout(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive accepts large timeout values."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.return_value = b"data"

            await conn.receive(timeout=3600.0)

            call_args = mock_wait_for.call_args
            assert call_args[1]["timeout"] == 3600.0

    # -------------------------------------------------------------------------
    # Error handling - unexpected read errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_propagates_unexpected_exception_from_read(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive propagates unexpected exceptions from stdout.read."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = RuntimeError("Unexpected read error")

            with pytest.raises(RuntimeError, match="Unexpected read error"):
                await conn.receive()

    @pytest.mark.asyncio
    async def test_propagates_connection_closed_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Receive propagates connection closed errors."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = BrokenPipeError("Connection closed")

            with pytest.raises(BrokenPipeError, match="Connection closed"):
                await conn.receive()

    # -------------------------------------------------------------------------
    # Logging - no logging expected for simple data read
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_does_not_log_on_successful_receive(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Receive does not produce log output on successful read."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=b"data")

        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            await conn.receive()

        # No logs expected for simple data read (would be too noisy)
        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_does_not_log_on_timeout(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Receive does not log on timeout (normal operation)."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for") as mock_wait_for:
            mock_wait_for.side_effect = TimeoutError()

            with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
                await conn.receive()

        # No logs expected - timeout is expected behavior
        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_does_not_log_on_not_connected_error(self, valid_connection_params, caplog):
        """Receive does not log when raising not connected error."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = None

        with (
            caplog.at_level(logging.DEBUG, logger="engine.ssh"),
            pytest.raises(SSHConnectionError),
        ):
            await conn.receive()

        # No logs expected - error is raised to caller
        assert caplog.text == ""
