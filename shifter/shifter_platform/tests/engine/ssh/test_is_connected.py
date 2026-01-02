"""Tests for SSHConnection.is_connected property."""

import logging

import pytest

from engine.ssh import SSHConnection


class TestSSHConnectionIsConnected:
    """Tests for SSHConnection.is_connected property."""

    # -------------------------------------------------------------------------
    # Happy path - returns expected output
    # -------------------------------------------------------------------------

    def test_returns_true_when_connection_exists_and_not_closed(
        self, valid_connection_params, mock_asyncssh_connection
    ):
        """is_connected returns True when connection exists and is not closed."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        result = conn.is_connected

        assert result is True

    def test_returns_false_when_connection_is_none(self, valid_connection_params):
        """is_connected returns False when connection is None."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None

        result = conn.is_connected

        assert result is False

    def test_returns_false_when_connection_is_closed(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected returns False when connection exists but is closed."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = True

        result = conn.is_connected

        assert result is False

    def test_returns_false_after_initialization(self, valid_connection_params):
        """is_connected returns False immediately after initialization."""
        conn = SSHConnection(**valid_connection_params)

        result = conn.is_connected

        assert result is False

    def test_returns_boolean_type(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected returns a boolean type."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        result = conn.is_connected

        assert isinstance(result, bool)

    # -------------------------------------------------------------------------
    # Input validation - property uses internal state
    # -------------------------------------------------------------------------

    def test_calls_is_closed_on_connection(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected checks is_closed() on the connection object."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        _ = conn.is_connected

        mock_asyncssh_connection.is_closed.assert_called_once()

    def test_does_not_call_is_closed_when_conn_is_none(self, valid_connection_params):
        """is_connected short-circuits when connection is None."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None

        # This should not raise even though we can't call is_closed on None
        result = conn.is_connected

        assert result is False

    # -------------------------------------------------------------------------
    # Side effects - none expected (read-only property)
    # -------------------------------------------------------------------------

    def test_is_read_only_property(self, valid_connection_params):
        """is_connected is a read-only property that cannot be set."""
        conn = SSHConnection(**valid_connection_params)

        with pytest.raises(AttributeError):
            conn.is_connected = True  # type: ignore

    def test_does_not_modify_connection_state(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected does not modify the connection state."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        _ = conn.is_connected

        # Connection reference should remain unchanged
        assert conn._conn is mock_asyncssh_connection

    def test_does_not_modify_process_state(
        self, valid_connection_params, mock_asyncssh_connection, mock_asyncssh_process
    ):
        """is_connected does not modify the process state."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = mock_asyncssh_process
        mock_asyncssh_connection.is_closed.return_value = False

        _ = conn.is_connected

        # Process reference should remain unchanged
        assert conn._process is mock_asyncssh_process

    # -------------------------------------------------------------------------
    # Error handling - propagates exceptions
    # -------------------------------------------------------------------------

    def test_propagates_exception_from_is_closed(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected propagates exceptions from is_closed()."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.side_effect = RuntimeError("Connection error")

        with pytest.raises(RuntimeError, match="Connection error"):
            _ = conn.is_connected

    def test_propagates_attribute_error_from_connection(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected propagates AttributeError if is_closed missing."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.side_effect = AttributeError("No is_closed")

        with pytest.raises(AttributeError, match="No is_closed"):
            _ = conn.is_connected

    # -------------------------------------------------------------------------
    # Logging - no logging expected for simple property access
    # -------------------------------------------------------------------------

    def test_does_not_log_on_property_access(self, valid_connection_params, mock_asyncssh_connection, caplog):
        """is_connected does not produce log output on access."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            _ = conn.is_connected

        # No logs expected for simple property access
        assert caplog.text == ""

    def test_does_not_log_when_not_connected(self, valid_connection_params, caplog):
        """is_connected does not log when returning False."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = None

        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            _ = conn.is_connected

        # No logs expected for simple property access
        assert caplog.text == ""

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_handles_is_closed_returning_truthy_value(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected handles truthy non-boolean from is_closed()."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = 1  # Truthy but not True

        result = conn.is_connected

        assert result is False

    def test_handles_is_closed_returning_falsy_value(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected handles falsy non-boolean from is_closed()."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = 0  # Falsy but not False

        result = conn.is_connected

        assert result is True

    def test_can_be_checked_multiple_times(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected can be checked multiple times without side effects."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False

        result1 = conn.is_connected
        result2 = conn.is_connected
        result3 = conn.is_connected

        assert result1 is True
        assert result2 is True
        assert result3 is True
        assert mock_asyncssh_connection.is_closed.call_count == 3

    def test_reflects_connection_state_changes(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected reflects changes in connection state over time."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection

        # Initially not closed
        mock_asyncssh_connection.is_closed.return_value = False
        assert conn.is_connected is True

        # Then connection closes
        mock_asyncssh_connection.is_closed.return_value = True
        assert conn.is_connected is False

    def test_reflects_connection_reference_changes(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected reflects changes in connection reference."""
        conn = SSHConnection(**valid_connection_params)

        # Initially no connection
        assert conn.is_connected is False

        # Connection established
        conn._conn = mock_asyncssh_connection
        mock_asyncssh_connection.is_closed.return_value = False
        assert conn.is_connected is True

        # Connection cleared
        conn._conn = None
        assert conn.is_connected is False

    def test_ignores_process_state(self, valid_connection_params, mock_asyncssh_connection):
        """is_connected only checks connection, not process state."""
        conn = SSHConnection(**valid_connection_params)
        conn._conn = mock_asyncssh_connection
        conn._process = None  # Process is None but connection exists
        mock_asyncssh_connection.is_closed.return_value = False

        result = conn.is_connected

        # Should still be True because connection exists
        assert result is True
