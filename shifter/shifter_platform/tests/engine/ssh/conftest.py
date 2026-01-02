"""Shared fixtures for SSH connection tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

# Sample RSA private key for testing (not a real key - just valid format)
VALID_PRIVATE_KEY = """TEST_SSH_PRIVATE_KEY"""


@pytest.fixture
def valid_connection_params():
    """Return valid parameters for SSHConnection initialization."""
    return {
        "host": "10.0.0.1",
        "username": "testuser",
        "private_key": VALID_PRIVATE_KEY,
    }


@pytest.fixture
def valid_connection_params_with_options():
    """Return valid parameters with all optional values specified."""
    return {
        "host": "10.0.0.1",
        "username": "testuser",
        "private_key": VALID_PRIVATE_KEY,
        "port": 2222,
        "term_type": "vt100",
        "term_size": (120, 40),
    }


@pytest.fixture
def mock_asyncssh_connection():
    """Return a mock asyncssh connection object."""
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


@pytest.fixture
def mock_asyncssh_process():
    """Return a mock asyncssh process object."""
    process = AsyncMock()
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdout = AsyncMock()
    process.stdout.read = AsyncMock(return_value=b"test output")
    process.close = MagicMock()
    process.change_terminal_size = MagicMock()
    return process


@pytest.fixture
def mock_private_key():
    """Return a mock private key object."""
    return MagicMock()
