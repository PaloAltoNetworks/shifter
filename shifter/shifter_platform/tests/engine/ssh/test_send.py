"""Tests for SSHConnection.send."""

import logging

import pytest

from engine.ssh import SSHConnection, SSHConnectionError


class TestSSHConnectionSend:
    """Tests for SSHConnection.send method."""

    # -------------------------------------------------------------------------
    # Happy path - send succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_writes_data_to_stdin(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Send writes data to the process stdin."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"ls -la\n"

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_empty_bytes(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Send can send empty bytes."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b""

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_single_byte(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Send can send a single byte."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"a"

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_large_data(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Send can send large amounts of data."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"x" * 65536  # 64KB

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_binary_data(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Send can send arbitrary binary data."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = bytes(range(256))  # All possible byte values

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_control_characters(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send can send control characters."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"\x03"  # Ctrl+C

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_newline_characters(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send can send various newline characters."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"line1\nline2\r\nline3\r"

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    # -------------------------------------------------------------------------
    # Error handling - not connected
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_error_when_not_connected(self, valid_connection_params):
        """Send raises SSHConnectionError when not connected."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = None

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.send(b"data")

    @pytest.mark.asyncio
    async def test_raises_error_when_process_is_none(self, valid_connection_params, mock_asyncssh_connection):
        """Send raises SSHConnectionError when process is None."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = None

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.send(b"data")

    # -------------------------------------------------------------------------
    # Multiple sends
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_can_send_multiple_times(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send can be called multiple times in succession."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.send(b"cmd1\n")
        await conn.send(b"cmd2\n")
        await conn.send(b"cmd3\n")

        assert mock_asyncssh_process.stdin.write.call_count == 3

    @pytest.mark.asyncio
    async def test_preserves_data_order_in_multiple_sends(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send preserves data order when called multiple times."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.send(b"first\n")
        await conn.send(b"second\n")
        await conn.send(b"third\n")

        calls = mock_asyncssh_process.stdin.write.call_args_list
        assert calls[0][0][0] == b"first\n"
        assert calls[1][0][0] == b"second\n"
        assert calls[2][0][0] == b"third\n"

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sends_utf8_encoded_text(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send can send UTF-8 encoded text."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = "echo 'héllo wörld'".encode()

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_sends_escape_sequences(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send can send ANSI escape sequences."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        data = b"\x1b[H\x1b[2J"  # Clear screen sequence

        await conn.send(data)

        mock_asyncssh_process.stdin.write.assert_called_once_with(data)

    # -------------------------------------------------------------------------
    # Output - return value
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_none_on_success(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send returns None on successful write."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        result = await conn.send(b"data")

        assert result is None

    # -------------------------------------------------------------------------
    # Error handling - stdin write failures
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_propagates_exception_from_stdin_write(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send propagates exceptions from stdin.write."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdin.write.side_effect = BrokenPipeError("Pipe closed")

        with pytest.raises(BrokenPipeError, match="Pipe closed"):
            await conn.send(b"data")

    @pytest.mark.asyncio
    async def test_propagates_os_error_from_stdin_write(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Send propagates OSError from stdin.write."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdin.write.side_effect = OSError("Write failed")

        with pytest.raises(OSError, match="Write failed"):
            await conn.send(b"data")

    # -------------------------------------------------------------------------
    # Logging - no logging expected for simple data write
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_does_not_log_on_successful_send(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Send does not produce log output on successful write."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            await conn.send(b"data")

        # No logs expected for simple data write (would be too noisy)
        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_does_not_log_on_not_connected_error(self, valid_connection_params, caplog):
        """Send does not log when raising not connected error."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = None

        with (
            caplog.at_level(logging.DEBUG, logger="engine.ssh"),
            pytest.raises(SSHConnectionError),
        ):
            await conn.send(b"data")

        # No logs expected - error is raised to caller
        assert caplog.text == ""
