"""Tests for SSHConnection.

Integration-style tests covering the SSH connection lifecycle:
connect, send, receive, resize, disconnect.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from engine.ssh import SSHConnection, SSHConnectionError


class TestSSHConnectionInit:
    """Tests for SSHConnection initialization."""

    def test_stores_connection_params(self, valid_connection_params):
        """Constructor stores all connection parameters."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.host == "10.0.0.1"
        assert conn.username == "testuser"
        assert conn.private_key == valid_connection_params["private_key"]
        assert conn.port == 22
        assert conn.term_type == "xterm-256color"
        assert conn.term_size == (80, 24)

    def test_accepts_custom_options(self, valid_connection_params):
        """Constructor accepts custom port and terminal settings."""
        conn = SSHConnection(
            **valid_connection_params,
            port=2222,
            term_type="vt100",
            term_size=(120, 40),
        )

        assert conn.port == 2222
        assert conn.term_type == "vt100"
        assert conn.term_size == (120, 40)

    def test_accepts_session_id(self, valid_connection_params):
        """Constructor accepts session_id for persistent tmux sessions."""
        conn = SSHConnection(
            **valid_connection_params,
            session_id="test-session-123",
        )

        assert conn.session_id == "test-session-123"

    def test_session_id_defaults_to_none(self, valid_connection_params):
        """session_id defaults to None when not provided."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.session_id is None


class TestSSHConnectionConnect:
    """Tests for connect() method."""

    @pytest.mark.asyncio
    async def test_successful_connect(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Successful connect establishes connection and creates PTY process."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_key = MagicMock()
            mock_asyncssh.import_private_key = MagicMock(return_value=mock_key)
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            # Key imported
            mock_asyncssh.import_private_key.assert_called_once_with(valid_connection_params["private_key"])
            # Connected with correct params
            mock_asyncssh.connect.assert_called_once_with(
                "10.0.0.1",
                port=22,
                username="testuser",
                client_keys=[mock_key],
                known_hosts=None,
            )
            # PTY process created with no command (default shell)
            mock_asyncssh_connection.create_process.assert_called_once_with(
                None,  # No command = default shell
                term_type="xterm-256color",
                term_size=(80, 24),
                encoding=None,
            )

    @pytest.mark.asyncio
    async def test_connect_with_custom_port(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Connect uses custom port when specified."""
        conn = SSHConnection(**valid_connection_params, port=2222)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            assert mock_asyncssh.connect.call_args[1]["port"] == 2222

    @pytest.mark.asyncio
    async def test_connect_with_session_id_uses_tmux(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Connect with session_id runs tmux new-session command."""
        conn = SSHConnection(**valid_connection_params, session_id="test-uuid-1234")

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            # Verify tmux command is passed
            mock_asyncssh_connection.create_process.assert_called_once_with(
                "tmux new-session -A -s test-uuid-1234",
                term_type="xterm-256color",
                term_size=(80, 24),
                encoding=None,
            )

    @pytest.mark.asyncio
    async def test_connect_sanitizes_session_id(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Connect sanitizes session_id to alphanumeric and hyphens only."""
        # Session ID with special characters that could be problematic
        conn = SSHConnection(**valid_connection_params, session_id="test/session;rm -rf")

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            # Verify special chars are replaced with hyphens
            call_args = mock_asyncssh_connection.create_process.call_args[0]
            assert call_args[0] == "tmux new-session -A -s test-session-rm--rf"

    @pytest.mark.asyncio
    async def test_connect_permission_denied(self, valid_connection_params):
        """Permission denied raises SSHConnectionError."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(side_effect=asyncssh.PermissionDenied("Auth failed"))
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied

            with pytest.raises(SSHConnectionError, match="authentication failed"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_connect_network_error(self, valid_connection_params):
        """Network error raises SSHConnectionError."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch(
                "engine.ssh.asyncssh.import_private_key",
                return_value=MagicMock(),
            ),
            patch(
                "engine.ssh.asyncssh.connect",
                AsyncMock(side_effect=OSError("Connection refused")),
            ),
            pytest.raises(SSHConnectionError, match="Network error"),
        ):
            await conn.connect()


class TestSSHConnectionDisconnect:
    """Tests for disconnect() method."""

    @pytest.mark.asyncio
    async def test_closes_process_and_connection(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Disconnect closes process and connection."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        mock_asyncssh_process.close.assert_called_once()
        mock_asyncssh_connection.close.assert_called_once()
        mock_asyncssh_connection.wait_closed.assert_awaited_once()
        assert conn._conn is None
        assert conn._process is None

    @pytest.mark.asyncio
    async def test_handles_disconnect_without_connect(self, valid_connection_params):
        """Disconnect handles case where connect never completed."""
        conn = SSHConnection(**valid_connection_params)

        await conn.disconnect()  # Should not raise


class TestSSHConnectionSend:
    """Tests for send() method."""

    @pytest.mark.asyncio
    async def test_writes_to_stdin(
        self,
        valid_connection_params,
        mock_asyncssh_process,
    ):
        """Send writes data to process stdin."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = mock_asyncssh_process

        await conn.send(b"ls -la\n")

        mock_asyncssh_process.stdin.write.assert_called_once_with(b"ls -la\n")

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self, valid_connection_params):
        """Send raises SSHConnectionError when not connected."""
        conn = SSHConnection(**valid_connection_params)

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.send(b"test")


class TestSSHConnectionReceive:
    """Tests for receive() method."""

    @pytest.mark.asyncio
    async def test_reads_from_stdout(
        self,
        valid_connection_params,
        mock_asyncssh_process,
    ):
        """Receive reads data from process stdout."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.stdout.read = AsyncMock(return_value=b"output data")

        result = await conn.receive()

        assert result == b"output data"
        mock_asyncssh_process.stdout.read.assert_awaited_once_with(4096)

    @pytest.mark.asyncio
    async def test_returns_empty_on_timeout(
        self,
        valid_connection_params,
        mock_asyncssh_process,
    ):
        """Receive returns empty bytes on timeout."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = mock_asyncssh_process

        with patch("engine.ssh.asyncio.wait_for", side_effect=TimeoutError()):
            result = await conn.receive()

        assert result == b""

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self, valid_connection_params):
        """Receive raises SSHConnectionError when not connected."""
        conn = SSHConnection(**valid_connection_params)

        with pytest.raises(SSHConnectionError, match="Not connected"):
            await conn.receive()


class TestSSHConnectionResize:
    """Tests for resize() method."""

    @pytest.mark.asyncio
    async def test_changes_terminal_size(
        self,
        valid_connection_params,
        mock_asyncssh_process,
    ):
        """Resize changes terminal size on process."""
        conn = SSHConnection(**valid_connection_params)
        conn._process = mock_asyncssh_process

        await conn.resize(120, 40)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(120, 40)
        assert conn.term_size == (120, 40)


class TestSSHConnectionIsConnected:
    """Tests for is_connected property."""

    def test_reflects_connection_state(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
    ):
        """is_connected reflects actual connection state."""
        conn = SSHConnection(**valid_connection_params)

        # False when no connection
        assert conn.is_connected is False

        # False when connection is closed
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = True
        assert conn.is_connected is False

        # True when connection is active
        mock_asyncssh_connection.is_closed.return_value = False
        assert conn.is_connected is True


class TestSSHConnectionContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_connects_and_disconnects(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
    ):
        """Context manager connects on entry and disconnects on exit."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            async with SSHConnection(**valid_connection_params) as conn:
                assert conn._conn is not None

            mock_asyncssh_connection.close.assert_called_once()
