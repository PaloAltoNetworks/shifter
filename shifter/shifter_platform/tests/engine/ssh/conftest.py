"""Shared fixtures for SSH connection tests."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Tests mock key import before opening a connection, so a literal private-key
# block is unnecessary and trips secret scanners.
VALID_PRIVATE_KEY = "TEST_SSH_PRIVATE_KEY"  # nosec B105  # NOSONAR


@pytest.fixture
def valid_connection_params():
    """Return valid parameters for SSHConnection initialization."""
    return {
        "host": "10.0.0.1",
        "username": "testuser",
        "private_key": VALID_PRIVATE_KEY,
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


@contextmanager
def patch_asyncssh(connection, *, imported_key=None):
    """Patch the real ``asyncssh`` library boundary (key import + connect).

    ``engine.ssh`` calls ``asyncssh.import_private_key`` and
    ``asyncssh.connect`` directly; patching the library functions exercises the
    real first-party connect logic over a mocked SSH transport boundary. Returns
    a namespace exposing the two mocks for call assertions. Exception classes on
    the real ``asyncssh`` module are left intact so ``except`` clauses match.
    """
    key = imported_key if imported_key is not None else MagicMock()
    with (
        patch("asyncssh.import_private_key", MagicMock(return_value=key)) as import_key,
        patch("asyncssh.connect", AsyncMock(return_value=connection)) as connect,
    ):
        yield SimpleNamespace(import_private_key=import_key, connect=connect, key=key)
