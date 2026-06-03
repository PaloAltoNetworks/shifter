"""Tests for SSHConsumer capacity controls (issue #847).

Covers the per-process / per-user session caps, the idle and max-duration
timeouts, and the non-busy-loop read behavior added to keep terminal websocket
load from destabilizing the portal during live events.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.enums import WebSocketCloseCode


@pytest.fixture(autouse=True)
def _reset_session_registry():
    """Reset the process-global session registry around each test.

    The registry is module-level (one per ASGI process in production). The
    consumer binds it as ``mission_control.consumers._session_registry`` (an
    alias of ``terminal_sessions.session_registry``); rebinding the consumer
    alias is what the integration tests read. Without the reset, a test that
    reserves a slot leaks counts into later tests and makes the cap assertions
    order-dependent.
    """
    from mission_control import consumers
    from mission_control.terminal_sessions import TerminalSessionRegistry

    consumers._session_registry = TerminalSessionRegistry()
    yield
    consumers._session_registry = TerminalSessionRegistry()


@pytest.fixture
def consumer():
    """An SSHConsumer with mocked WebSocket I/O methods."""
    from mission_control.consumers import SSHConsumer

    c = SSHConsumer()
    c.channel_name = "test-channel"
    c.close = AsyncMock()
    c.accept = AsyncMock()
    c.send = AsyncMock()
    return c


@pytest.fixture
def authenticated_scope():
    """WebSocket scope with an authenticated user."""
    user = MagicMock()
    user.id = 1
    user.is_authenticated = True
    return {
        "type": "websocket",
        "user": user,
        "url_route": {"kwargs": {"instance_uuid": "test-uuid-1234"}},
    }


class TestTerminalSessionRegistry:
    """Unit tests for the process-local session accounting."""

    @pytest.mark.asyncio
    async def test_acquire_and_release_total(self):
        from mission_control.terminal_sessions import TerminalSessionRegistry

        reg = TerminalSessionRegistry()
        assert await reg.try_acquire(1, max_total=2, max_per_user=10) is True
        assert await reg.try_acquire(2, max_total=2, max_per_user=10) is True
        # Third overall session exceeds the global cap.
        assert await reg.try_acquire(3, max_total=2, max_per_user=10) is False

        await reg.release(1)
        # A freed slot lets a new session in.
        assert await reg.try_acquire(3, max_total=2, max_per_user=10) is True

    @pytest.mark.asyncio
    async def test_per_user_cap(self):
        from mission_control.terminal_sessions import TerminalSessionRegistry

        reg = TerminalSessionRegistry()
        assert await reg.try_acquire(1, max_total=100, max_per_user=2) is True
        assert await reg.try_acquire(1, max_total=100, max_per_user=2) is True
        # Same user's third session is rejected even though global headroom exists.
        assert await reg.try_acquire(1, max_total=100, max_per_user=2) is False
        # A different user is unaffected.
        assert await reg.try_acquire(2, max_total=100, max_per_user=2) is True

    @pytest.mark.asyncio
    async def test_caps_disabled_when_non_positive(self):
        from mission_control.terminal_sessions import TerminalSessionRegistry

        reg = TerminalSessionRegistry()
        for _ in range(50):
            assert await reg.try_acquire(1, max_total=0, max_per_user=0) is True

    @pytest.mark.asyncio
    async def test_release_unknown_user_is_safe(self):
        from mission_control.terminal_sessions import TerminalSessionRegistry

        reg = TerminalSessionRegistry()
        # Releasing without a prior acquire must not underflow.
        await reg.release(999)
        assert reg.snapshot() == {"active_sessions": 0, "distinct_users": 0}


class TestSSHConsumerCapacity:
    """The consumer rejects over-cap connections and frees slots on exit."""

    @pytest.mark.asyncio
    async def test_rejects_when_session_cap_reached(self, consumer, authenticated_scope, settings):
        settings.TERMINAL_MAX_SESSIONS = 1
        settings.TERMINAL_MAX_SESSIONS_PER_USER = 100
        consumer.scope = authenticated_scope

        from mission_control import consumers as consumers_mod

        # Fill the single global slot with another session.
        await consumers_mod._session_registry.try_acquire(99, 1, 100)

        with patch("engine.services.connect_terminal") as mock_connect:
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVICE_UNAVAILABLE)
        # Rejected before any SSH work.
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_releases_slot_on_ssh_failure(self, consumer, authenticated_scope, settings):
        settings.TERMINAL_MAX_SESSIONS = 5
        settings.TERMINAL_MAX_SESSIONS_PER_USER = 5
        consumer.scope = authenticated_scope

        from mission_control import consumers as consumers_mod

        mock_ssh = AsyncMock()
        mock_ssh.connect.side_effect = ConnectionError("SSH failed")
        with patch("engine.services.connect_terminal", return_value=mock_ssh):
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)
        # The reserved slot was returned, so the registry is empty again.
        assert consumers_mod._session_registry.snapshot()["active_sessions"] == 0

    @pytest.mark.asyncio
    async def test_releases_slot_on_disconnect(self, consumer, settings):
        from mission_control import consumers as consumers_mod

        consumer._user_id = 1
        consumer._session_acquired = True
        await consumers_mod._session_registry.try_acquire(1, 5, 5)
        assert consumers_mod._session_registry.snapshot()["active_sessions"] == 1

        # disconnect() audits the session, which writes to the DB; patch it so
        # this stays a fast unit test focused on slot release.
        with patch("mission_control.consumers.audit_session_event"):
            await consumer.disconnect(close_code=1000)

        assert consumers_mod._session_registry.snapshot()["active_sessions"] == 0

    @pytest.mark.asyncio
    async def test_release_is_idempotent(self, consumer, settings):
        from mission_control import consumers as consumers_mod

        consumer._user_id = 1
        consumer._session_acquired = True
        await consumers_mod._session_registry.try_acquire(1, 5, 5)

        await consumer._release_session_slot()
        await consumer._release_session_slot()

        assert consumers_mod._session_registry.snapshot()["active_sessions"] == 0


class TestSSHConsumerReadLoop:
    """The read loop stops on EOF and on the idle / max-duration limits."""

    @pytest.mark.asyncio
    async def test_breaks_on_eof(self, consumer, settings):
        settings.TERMINAL_READ_POLL_SECONDS = 1
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0
        settings.TERMINAL_MAX_SESSION_SECONDS = 0
        consumer.instance_uuid = "test"

        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive = AsyncMock(return_value=b"")
        mock_ssh.at_eof = MagicMock(return_value=True)
        consumer.ssh_conn = mock_ssh

        await consumer._read_ssh_output()

        mock_ssh.receive.assert_awaited_once_with(timeout=1)
        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_breaks_on_idle_timeout(self, consumer, settings):
        settings.TERMINAL_READ_POLL_SECONDS = 1
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 60
        settings.TERMINAL_MAX_SESSION_SECONDS = 0
        consumer.instance_uuid = "test"

        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive = AsyncMock(return_value=b"")
        mock_ssh.at_eof = MagicMock(return_value=False)
        consumer.ssh_conn = mock_ssh

        loop = asyncio.get_running_loop()
        # Last activity well beyond the idle window.
        consumer._last_activity = loop.time() - 10_000
        consumer._session_start = loop.time()

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_breaks_on_max_duration(self, consumer, settings):
        settings.TERMINAL_READ_POLL_SECONDS = 1
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0
        settings.TERMINAL_MAX_SESSION_SECONDS = 60
        consumer.instance_uuid = "test"

        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive = AsyncMock(return_value=b"")
        mock_ssh.at_eof = MagicMock(return_value=False)
        consumer.ssh_conn = mock_ssh

        loop = asyncio.get_running_loop()
        consumer._last_activity = loop.time()
        # Session started long before the max-duration window.
        consumer._session_start = loop.time() - 10_000

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forwards_output_and_records_activity(self, consumer, settings):
        settings.TERMINAL_READ_POLL_SECONDS = 1
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0
        settings.TERMINAL_MAX_SESSION_SECONDS = 0
        consumer.instance_uuid = "test"

        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(side_effect=[b"hello", b""])
        mock_ssh.at_eof = MagicMock(return_value=True)
        consumer.ssh_conn = mock_ssh

        # is_connected: True for two iterations, then False.
        calls = [0]

        def _connected():
            calls[0] += 1
            return calls[0] <= 2

        type(mock_ssh).is_connected = property(lambda _self: _connected())

        await consumer._read_ssh_output()

        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["type"] == "output"
        assert message["data"] == "hello"
