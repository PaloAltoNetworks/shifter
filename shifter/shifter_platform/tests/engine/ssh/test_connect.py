"""Tests for SSHConnection.connect."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from engine.ssh import SSHConnection, SSHConnectionError


class TestSSHConnectionConnect:
    """Tests for SSHConnection.connect method."""

    # -------------------------------------------------------------------------
    # Happy path - connection succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_imports_private_key(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Connect imports the private key using asyncssh."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            mock_asyncssh.import_private_key.assert_called_once_with(valid_connection_params["private_key"])

    @pytest.mark.asyncio
    async def test_connects_to_ssh_server_with_correct_parameters(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect calls asyncssh.connect with correct host, port, username, and key."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_key = MagicMock()
            mock_asyncssh.import_private_key = MagicMock(return_value=mock_key)
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            mock_asyncssh.connect.assert_called_once_with(
                valid_connection_params["host"],
                port=22,
                username=valid_connection_params["username"],
                client_keys=[mock_key],
                known_hosts=None,
            )

    @pytest.mark.asyncio
    async def test_connects_with_custom_port(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect uses custom port when specified."""
        conn = SSHConnection(**valid_connection_params, port=2222)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            call_kwargs = mock_asyncssh.connect.call_args[1]
            assert call_kwargs["port"] == 2222

    @pytest.mark.asyncio
    async def test_creates_process_with_pty(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect creates process with PTY using correct terminal settings."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            mock_asyncssh_connection.create_process.assert_called_once_with(
                term_type="xterm-256color",
                term_size=(80, 24),
                encoding=None,
            )

    @pytest.mark.asyncio
    async def test_creates_process_with_custom_terminal_settings(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect uses custom terminal type and size when specified."""
        conn = SSHConnection(**valid_connection_params, term_type="vt100", term_size=(120, 40))

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            mock_asyncssh_connection.create_process.assert_called_once_with(
                term_type="vt100",
                term_size=(120, 40),
                encoding=None,
            )

    @pytest.mark.asyncio
    async def test_stores_connection_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect stores the connection object internally."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            assert conn._conn is mock_asyncssh_connection

    @pytest.mark.asyncio
    async def test_stores_process_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect stores the process object internally."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            await conn.connect()

            assert conn._process is mock_asyncssh_process

    # -------------------------------------------------------------------------
    # Error handling - disconnect errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_ssh_connection_error_on_disconnect_error(self, valid_connection_params):
        """Connect raises SSHConnectionError when asyncssh.DisconnectError occurs."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = asyncssh.DisconnectError(1, "Disconnected")

            with pytest.raises(SSHConnectionError, match="SSH connection failed"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_wraps_disconnect_error_as_cause(self, valid_connection_params):
        """Connect preserves original DisconnectError as cause."""
        conn = SSHConnection(**valid_connection_params)
        original_error = asyncssh.DisconnectError(1, "Disconnected")

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = original_error

            with pytest.raises(SSHConnectionError) as exc_info:
                await conn.connect()

            assert exc_info.value.__cause__ is original_error

    # -------------------------------------------------------------------------
    # Error handling - permission denied errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_ssh_connection_error_on_permission_denied(self, valid_connection_params):
        """Connect raises SSHConnectionError when authentication fails."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = asyncssh.PermissionDenied("Authentication failed")

            with pytest.raises(SSHConnectionError, match="SSH authentication failed"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_wraps_permission_denied_as_cause(self, valid_connection_params):
        """Connect preserves original PermissionDenied as cause."""
        conn = SSHConnection(**valid_connection_params)
        original_error = asyncssh.PermissionDenied("Authentication failed")

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = original_error

            with pytest.raises(SSHConnectionError) as exc_info:
                await conn.connect()

            assert exc_info.value.__cause__ is original_error

    # -------------------------------------------------------------------------
    # Error handling - key import errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_ssh_connection_error_on_key_import_error(self, valid_connection_params):
        """Connect raises SSHConnectionError when key format is invalid."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch.object(asyncssh, "import_private_key", side_effect=asyncssh.KeyImportError("Invalid key format")),
            pytest.raises(SSHConnectionError, match="Invalid SSH key format"),
        ):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_wraps_key_import_error_as_cause(self, valid_connection_params):
        """Connect preserves original KeyImportError as cause."""
        conn = SSHConnection(**valid_connection_params)
        original_error = asyncssh.KeyImportError("Invalid key format")

        with patch.object(asyncssh, "import_private_key", side_effect=original_error):
            with pytest.raises(SSHConnectionError) as exc_info:
                await conn.connect()

            assert exc_info.value.__cause__ is original_error

    # -------------------------------------------------------------------------
    # Error handling - network errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_ssh_connection_error_on_os_error(self, valid_connection_params):
        """Connect raises SSHConnectionError when network error occurs."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=OSError("Connection refused"))

            with pytest.raises(SSHConnectionError, match="Network error"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_wraps_os_error_as_cause(self, valid_connection_params):
        """Connect preserves original OSError as cause."""
        conn = SSHConnection(**valid_connection_params)
        original_error = OSError("Connection refused")

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=original_error)

            with pytest.raises(SSHConnectionError) as exc_info:
                await conn.connect()

            assert exc_info.value.__cause__ is original_error

    # -------------------------------------------------------------------------
    # Error handling - unexpected errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raises_ssh_connection_error_on_unexpected_error(self, valid_connection_params):
        """Connect raises SSHConnectionError when unexpected error occurs."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=RuntimeError("Unexpected error"))

            with pytest.raises(SSHConnectionError, match="Connection failed"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error_as_cause(self, valid_connection_params):
        """Connect preserves original unexpected error as cause."""
        conn = SSHConnection(**valid_connection_params)
        original_error = RuntimeError("Unexpected error")

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=original_error)

            with pytest.raises(SSHConnectionError) as exc_info:
                await conn.connect()

            assert exc_info.value.__cause__ is original_error

    # -------------------------------------------------------------------------
    # Logging - success
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_info_on_successful_connection(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Connect logs INFO when connection succeeds."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            with caplog.at_level(logging.INFO, logger="engine.ssh"):
                await conn.connect()

            assert "SSH connection established" in caplog.text
            assert valid_connection_params["username"] in caplog.text
            assert valid_connection_params["host"] in caplog.text

    # -------------------------------------------------------------------------
    # Logging - errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_error_on_disconnect_error(self, valid_connection_params, caplog):
        """Connect logs exception when DisconnectError occurs."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = asyncssh.DisconnectError(1, "Disconnected")

            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.connect()

            assert "disconnect error" in caplog.text.lower()
            assert valid_connection_params["host"] in caplog.text

    @pytest.mark.asyncio
    async def test_logs_error_on_permission_denied(self, valid_connection_params, caplog):
        """Connect logs exception when PermissionDenied occurs."""
        conn = SSHConnection(**valid_connection_params)

        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = asyncssh.PermissionDenied("Authentication failed")

            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.connect()

            assert "permission denied" in caplog.text.lower()
            assert valid_connection_params["username"] in caplog.text
            assert valid_connection_params["host"] in caplog.text

    @pytest.mark.asyncio
    async def test_logs_error_on_key_import_error(self, valid_connection_params, caplog):
        """Connect logs exception when KeyImportError occurs."""
        conn = SSHConnection(**valid_connection_params)

        with patch.object(asyncssh, "import_private_key", side_effect=asyncssh.KeyImportError("Invalid key format")):
            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.connect()

            assert "invalid ssh key" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_logs_error_on_network_error(self, valid_connection_params, caplog):
        """Connect logs exception when network error occurs."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=OSError("Connection refused"))

            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.connect()

            assert "network error" in caplog.text.lower()
            assert valid_connection_params["host"] in caplog.text

    @pytest.mark.asyncio
    async def test_logs_error_on_unexpected_error(self, valid_connection_params, caplog):
        """Connect logs exception when unexpected error occurs."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=RuntimeError("Unexpected error"))

            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.connect()

            assert "unexpected error" in caplog.text.lower()
            assert valid_connection_params["host"] in caplog.text

    # -------------------------------------------------------------------------
    # Output - return value
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_none_on_success(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Connect returns None on successful connection."""
        conn = SSHConnection(**valid_connection_params)

        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            result = await conn.connect()

            assert result is None
