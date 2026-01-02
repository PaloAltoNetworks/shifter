"""Tests for SSHConnection async context manager (__aenter__ and __aexit__)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from engine.ssh import SSHConnection, SSHConnectionError


class TestSSHConnectionAenter:
    """Tests for SSHConnection.__aenter__ method."""

    # -------------------------------------------------------------------------
    # Happy path - __aenter__ succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_calls_connect(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """__aenter__ calls connect method."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)
            await conn.__aenter__()

            # Verify connect was called by checking asyncssh.connect was called
            mock_asyncssh.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_self(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """__aenter__ returns the SSHConnection instance."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)
            result = await conn.__aenter__()

            assert result is conn

    @pytest.mark.asyncio
    async def test_returns_connected_instance(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aenter__ returns an instance that is connected."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)
            result = await conn.__aenter__()

            assert result._conn is not None
            assert result._process is not None

    # -------------------------------------------------------------------------
    # Error handling - connect failures
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_propagates_ssh_connection_error(self, valid_connection_params):
        """__aenter__ propagates SSHConnectionError from connect."""
        with patch.object(asyncssh, "import_private_key", side_effect=asyncssh.KeyImportError("Invalid key")):
            conn = SSHConnection(**valid_connection_params)

            with pytest.raises(SSHConnectionError):
                await conn.__aenter__()

    @pytest.mark.asyncio
    async def test_propagates_permission_denied_as_ssh_connection_error(self, valid_connection_params):
        """__aenter__ propagates PermissionDenied as SSHConnectionError."""
        with (
            patch.object(asyncssh, "import_private_key", return_value=MagicMock()),
            patch.object(asyncssh, "connect", new_callable=AsyncMock) as mock_connect,
        ):
            mock_connect.side_effect = asyncssh.PermissionDenied("Auth failed")

            conn = SSHConnection(**valid_connection_params)

            with pytest.raises(SSHConnectionError, match="authentication failed"):
                await conn.__aenter__()

    @pytest.mark.asyncio
    async def test_propagates_network_error_as_ssh_connection_error(self, valid_connection_params):
        """__aenter__ propagates network errors as SSHConnectionError."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.DisconnectError = asyncssh.DisconnectError
            mock_asyncssh.PermissionDenied = asyncssh.PermissionDenied
            mock_asyncssh.KeyImportError = asyncssh.KeyImportError
            mock_asyncssh.connect = AsyncMock(side_effect=OSError("Connection refused"))

            conn = SSHConnection(**valid_connection_params)

            with pytest.raises(SSHConnectionError, match="Network error"):
                await conn.__aenter__()

    # -------------------------------------------------------------------------
    # Side effects - state changes
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sets_connection_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aenter__ sets the _conn attribute."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)
            assert conn._conn is None

            await conn.__aenter__()

            assert conn._conn is mock_asyncssh_connection

    @pytest.mark.asyncio
    async def test_sets_process_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aenter__ sets the _process attribute."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)
            assert conn._process is None

            await conn.__aenter__()

            assert conn._process is mock_asyncssh_process

    # -------------------------------------------------------------------------
    # Logging - same as connect
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_info_on_successful_entry(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """__aenter__ logs INFO when connection succeeds."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            conn = SSHConnection(**valid_connection_params)

            with caplog.at_level(logging.INFO, logger="engine.ssh"):
                await conn.__aenter__()

            assert "SSH connection established" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_error_on_connection_failure(self, valid_connection_params, caplog):
        """__aenter__ logs ERROR when connection fails."""
        with patch.object(asyncssh, "import_private_key", side_effect=asyncssh.KeyImportError("Invalid key")):
            conn = SSHConnection(**valid_connection_params)

            with (
                caplog.at_level(logging.ERROR, logger="engine.ssh"),
                pytest.raises(SSHConnectionError),
            ):
                await conn.__aenter__()

            assert "invalid ssh key" in caplog.text.lower()


class TestSSHConnectionAexit:
    """Tests for SSHConnection.__aexit__ method."""

    # -------------------------------------------------------------------------
    # Happy path - __aexit__ succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_calls_disconnect(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """__aexit__ calls disconnect method."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.__aexit__(None, None, None)

        mock_asyncssh_process.close.assert_called_once()
        mock_asyncssh_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """__aexit__ returns None (does not suppress exceptions)."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        result = await conn.__aexit__(None, None, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_cleans_up_after_successful_block(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ cleans up connection after block completes normally."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.__aexit__(None, None, None)

        assert conn._conn is None
        assert conn._process is None

    # -------------------------------------------------------------------------
    # Error handling - exception in with block
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_disconnects_on_exception_in_block(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ disconnects even when exception occurred in block."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        # Simulate exception in block
        await conn.__aexit__(ValueError, ValueError("test error"), None)

        mock_asyncssh_process.close.assert_called_once()
        mock_asyncssh_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_suppress_exceptions(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ does not suppress exceptions from the with block."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        # None return means exception is not suppressed
        result = await conn.__aexit__(ValueError, ValueError("test error"), None)

        assert result is None  # None or False means don't suppress

    @pytest.mark.asyncio
    async def test_cleans_up_on_exception_in_block(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ cleans up connection even when exception in block."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.__aexit__(ValueError, ValueError("test"), None)

        assert conn._conn is None
        assert conn._process is None

    # -------------------------------------------------------------------------
    # Error handling - disconnect failures
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handles_disconnect_failure_gracefully(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ handles disconnect failures gracefully."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.close.side_effect = Exception("Close failed")

        # Should not raise
        await conn.__aexit__(None, None, None)

        # Should still clear references
        assert conn._conn is None
        assert conn._process is None

    # -------------------------------------------------------------------------
    # Side effects - state changes
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_clears_connection_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ clears the _conn attribute."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.__aexit__(None, None, None)

        assert conn._conn is None

    @pytest.mark.asyncio
    async def test_clears_process_reference(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """__aexit__ clears the _process attribute."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.__aexit__(None, None, None)

        assert conn._process is None

    # -------------------------------------------------------------------------
    # Logging - same as disconnect
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_info_on_successful_exit(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """__aexit__ logs INFO when disconnect succeeds."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with caplog.at_level(logging.INFO, logger="engine.ssh"):
            await conn.__aexit__(None, None, None)

        assert "SSH connection closed" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_error_on_disconnect_failure(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """__aexit__ logs ERROR when disconnect fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.close.side_effect = Exception("Close failed")

        with caplog.at_level(logging.ERROR, logger="engine.ssh"):
            await conn.__aexit__(None, None, None)

        assert "error closing" in caplog.text.lower()


class TestSSHConnectionContextManagerIntegration:
    """Integration tests for SSHConnection used as async context manager."""

    # -------------------------------------------------------------------------
    # Full context manager flow
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_disconnects(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Context manager connects on entry and disconnects on exit."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            async with SSHConnection(**valid_connection_params) as conn:
                # Inside block - should be connected
                assert conn._conn is not None
                assert conn._process is not None

            # After block - should be disconnected
            assert conn._conn is None
            assert conn._process is None

    @pytest.mark.asyncio
    async def test_context_manager_yields_connection_for_use(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Context manager yields a usable connection."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            async with SSHConnection(**valid_connection_params) as conn:
                # Should be able to use send and receive
                await conn.send(b"test")

            mock_asyncssh_process.stdin.write.assert_called_once_with(b"test")

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Context manager disconnects even when exception raised in block."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            with pytest.raises(RuntimeError, match="Test error"):
                async with SSHConnection(**valid_connection_params) as conn:
                    raise RuntimeError("Test error")

            # Should still be disconnected
            assert conn._conn is None
            assert conn._process is None

    @pytest.mark.asyncio
    async def test_context_manager_propagates_connect_error(self, valid_connection_params):
        """Context manager propagates connection errors on entry."""
        with (
            patch.object(asyncssh, "import_private_key", side_effect=asyncssh.KeyImportError("Invalid key")),
            pytest.raises(SSHConnectionError, match="Invalid SSH key format"),
        ):
            async with SSHConnection(**valid_connection_params):
                pass  # Should never reach here

    @pytest.mark.asyncio
    async def test_context_manager_logs_connection_lifecycle(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Context manager logs both connection and disconnection."""
        with patch("engine.ssh.asyncssh") as mock_asyncssh:
            mock_asyncssh.import_private_key = MagicMock(return_value=MagicMock())
            mock_asyncssh.connect = AsyncMock(return_value=mock_asyncssh_connection)
            mock_asyncssh_connection.create_process = AsyncMock(return_value=mock_asyncssh_process)

            with caplog.at_level(logging.INFO, logger="engine.ssh"):
                async with SSHConnection(**valid_connection_params):
                    pass

            assert "SSH connection established" in caplog.text
            assert "SSH connection closed" in caplog.text
