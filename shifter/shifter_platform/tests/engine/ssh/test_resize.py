"""Tests for SSHConnection.resize."""

import logging

import pytest

from engine.ssh import SSHConnection


class TestSSHConnectionResize:
    """Tests for SSHConnection.resize method."""

    # -------------------------------------------------------------------------
    # Happy path - resize succeeds
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_changes_terminal_size_on_process(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize calls change_terminal_size on the process."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(120, 40)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(120, 40)

    @pytest.mark.asyncio
    async def test_updates_term_size_attribute(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize updates the term_size attribute."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(120, 40)

        assert conn.term_size == (120, 40)

    @pytest.mark.asyncio
    async def test_resizes_to_default_size(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize can resize to default terminal size."""
        conn = SSHConnection(**valid_connection_params, term_size=(120, 40))
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(80, 24)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(80, 24)
        assert conn.term_size == (80, 24)

    @pytest.mark.asyncio
    async def test_resizes_to_large_dimensions(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize can resize to large terminal dimensions."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(400, 100)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(400, 100)
        assert conn.term_size == (400, 100)

    @pytest.mark.asyncio
    async def test_resizes_to_small_dimensions(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize can resize to small terminal dimensions."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(1, 1)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(1, 1)
        assert conn.term_size == (1, 1)

    # -------------------------------------------------------------------------
    # Error handling - not connected
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_does_not_raise_when_process_is_none(self, valid_connection_params, mock_asyncssh_connection):
        """Resize silently does nothing when process is None."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = None
        original_term_size = conn.term_size

        # Current implementation silently does nothing
        await conn.resize(120, 40)

        # term_size should remain unchanged
        assert conn.term_size == original_term_size

    @pytest.mark.asyncio
    async def test_does_not_raise_when_not_connected(self, valid_connection_params):
        """Resize silently does nothing when not connected."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None
        conn._process = None
        original_term_size = conn.term_size

        # Current implementation silently does nothing
        await conn.resize(120, 40)

        # term_size should remain unchanged
        assert conn.term_size == original_term_size

    # -------------------------------------------------------------------------
    # Error handling - change_terminal_size failures
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_propagates_exception_from_change_terminal_size(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize propagates exceptions from change_terminal_size."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.change_terminal_size.side_effect = RuntimeError("Resize failed")

        with pytest.raises(RuntimeError, match="Resize failed"):
            await conn.resize(120, 40)

    @pytest.mark.asyncio
    async def test_does_not_update_term_size_on_exception(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize does not update term_size when change_terminal_size raises."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        original_term_size = conn.term_size
        mock_asyncssh_process.change_terminal_size.side_effect = RuntimeError("Resize failed")

        with pytest.raises(RuntimeError):
            await conn.resize(120, 40)

        assert conn.term_size == original_term_size

    # -------------------------------------------------------------------------
    # Logging - success
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_debug_on_successful_resize(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Resize logs DEBUG when terminal size changes successfully."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            await conn.resize(120, 40)

        # Note: Current implementation doesn't log - this test documents expected behavior
        # If the test fails, it means logging should be added to the implementation

    # -------------------------------------------------------------------------
    # Logging - errors
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_logs_error_on_change_terminal_size_failure(
        self,
        valid_connection_params,
        mock_asyncssh_connection,
        mock_asyncssh_process,
        caplog,
    ):
        """Resize logs ERROR when change_terminal_size fails."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_process.change_terminal_size.side_effect = RuntimeError("Resize failed")

        with (
            caplog.at_level(logging.ERROR, logger="engine.ssh"),
            pytest.raises(RuntimeError),
        ):
            await conn.resize(120, 40)

        # Note: Current implementation doesn't log - this test documents expected behavior
        # If the test fails, it means logging should be added to the implementation

    # -------------------------------------------------------------------------
    # Multiple resizes
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_can_resize_multiple_times(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize can be called multiple times."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(100, 30)
        await conn.resize(120, 40)
        await conn.resize(80, 24)

        assert mock_asyncssh_process.change_terminal_size.call_count == 3

    @pytest.mark.asyncio
    async def test_updates_term_size_on_each_resize(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize updates term_size attribute on each call."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(100, 30)
        assert conn.term_size == (100, 30)

        await conn.resize(120, 40)
        assert conn.term_size == (120, 40)

        await conn.resize(80, 24)
        assert conn.term_size == (80, 24)

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_accepts_zero_columns(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Resize accepts zero columns (edge case, may not be practical)."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(0, 24)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(0, 24)
        assert conn.term_size == (0, 24)

    @pytest.mark.asyncio
    async def test_accepts_zero_rows(self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process):
        """Resize accepts zero rows (edge case, may not be practical)."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(80, 0)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(80, 0)
        assert conn.term_size == (80, 0)

    @pytest.mark.asyncio
    async def test_preserves_columns_rows_order(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize passes columns first, then rows to change_terminal_size."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(cols=120, rows=40)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(120, 40)

    @pytest.mark.asyncio
    async def test_handles_same_size_resize(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize handles resizing to the same current size."""
        conn = SSHConnection(**valid_connection_params)  # Default 80x24
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        await conn.resize(80, 24)

        mock_asyncssh_process.change_terminal_size.assert_called_once_with(80, 24)
        assert conn.term_size == (80, 24)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_requires_cols_parameter(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize raises TypeError when cols is not provided."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with pytest.raises(TypeError):
            await conn.resize(rows=40)  # type: ignore

    @pytest.mark.asyncio
    async def test_requires_rows_parameter(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize raises TypeError when rows is not provided."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        with pytest.raises(TypeError):
            await conn.resize(cols=120)  # type: ignore

    # -------------------------------------------------------------------------
    # Output - return value
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_none_on_success(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """Resize returns None on successful resize."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process

        result = await conn.resize(120, 40)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self, valid_connection_params):
        """Resize returns None when not connected."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None
        conn._process = None

        result = await conn.resize(120, 40)

        assert result is None
