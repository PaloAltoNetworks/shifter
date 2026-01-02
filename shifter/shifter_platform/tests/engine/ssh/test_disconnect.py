"""Tests for SSHConnection.disconnect."""

import logging

import pytest

from engine.ssh import SSHConnection


class TestSSHConnectionDisconnect:
    """Tests for SSHConnection.disconnect method."""

    # -------------------------------------------------------------------------
    # Happy path - disconnect succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_closes_process_when_exists(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect closes the process when it exists."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        mock_asyncssh_process.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_process_reference_when_exists(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect clears the process reference after closing."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        assert conn._process is None

    @pytest.mark.asyncio
    async def test_closes_connection_when_exists(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect closes the connection when it exists."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        mock_asyncssh_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_waits_for_connection_to_close(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect waits for the connection to fully close."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        mock_asyncssh_connection.wait_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_connection_reference_when_exists(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect clears the connection reference after closing."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()

        assert conn._conn is None

    @pytest.mark.asyncio
    async def test_handles_no_process(self, valid_connection_params, mock_asyncssh_connection):
        """Disconnect handles missing process gracefully."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = None

        await conn.disconnect()

        assert conn._conn is None

    @pytest.mark.asyncio
    async def test_handles_no_connection(self, valid_connection_params):
        """Disconnect handles missing connection gracefully."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None
        conn._process = None

        # Should not raise
        await conn.disconnect()

        assert conn._conn is None
        assert conn._process is None

    @pytest.mark.asyncio
    async def test_closes_process_before_connection(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect closes process before closing connection."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        call_order = []
        mock_asyncssh_process.close.side_effect = lambda: call_order.append("process")
        mock_asyncssh_connection.close.side_effect = lambda: call_order.append("connection")

        await conn.disconnect()

        assert call_order == ["process", "connection"]

    # -------------------------------------------------------------------------
    # Error handling - process close errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_clears_references_on_process_close_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect clears references even when process close fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.close.side_effect = Exception("Close failed")

        await conn.disconnect()

        assert conn._process is None
        assert conn._conn is None

    @pytest.mark.asyncio
    async def test_clears_references_on_connection_close_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect clears references even when connection close fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.close.side_effect = Exception("Close failed")

        await conn.disconnect()

        assert conn._process is None
        assert conn._conn is None

    @pytest.mark.asyncio
    async def test_clears_references_on_wait_closed_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect clears references even when wait_closed fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.wait_closed.side_effect = Exception("Wait failed")

        await conn.disconnect()

        assert conn._process is None
        assert conn._conn is None

    # -------------------------------------------------------------------------
    # Logging - success
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_info_on_successful_disconnect(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Disconnect logs INFO when connection closes successfully."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with caplog.at_level(logging.INFO, logger="engine.ssh"):
            await conn.disconnect()

        assert "SSH connection closed" in caplog.text
        assert valid_connection_params["host"] in caplog.text

    # -------------------------------------------------------------------------
    # Logging - errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_error_on_close_failure(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Disconnect logs exception when close fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.close.side_effect = Exception("Close failed")

        with caplog.at_level(logging.ERROR, logger="engine.ssh"):
            await conn.disconnect()

        assert "error closing" in caplog.text.lower()
        assert valid_connection_params["host"] in caplog.text

    # -------------------------------------------------------------------------
    # Idempotency - multiple calls
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_can_be_called_multiple_times(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect can be called multiple times without error."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()
        await conn.disconnect()  # Should not raise

        assert conn._conn is None
        assert conn._process is None

    @pytest.mark.asyncio
    async def test_only_closes_process_once(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect only closes the process once even when called multiple times."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()
        await conn.disconnect()

        mock_asyncssh_process.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_only_closes_connection_once(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect only closes the connection once even when called multiple times."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.disconnect()
        await conn.disconnect()

        mock_asyncssh_connection.close.assert_called_once()

    # -------------------------------------------------------------------------
    # Output - return value
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_none_on_success(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect returns None on successful close."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        result = await conn.disconnect()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self, valid_connection_params):
        """Disconnect returns None even when not connected."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None
        conn._process = None

        result = await conn.disconnect()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Disconnect returns None even when close fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.close.side_effect = Exception("Close failed")

        result = await conn.disconnect()

        assert result is None
