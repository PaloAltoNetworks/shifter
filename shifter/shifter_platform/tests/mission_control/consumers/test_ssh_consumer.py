"""Tests for SSHConsumer.

Integration-style tests covering the WebSocket consumer lifecycle:
connect, receive input, send output, disconnect.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from shared.enums import WebSocketCloseCode

User = get_user_model()


@pytest.fixture
def consumer():
    """Create an SSHConsumer with mocked WebSocket methods."""
    from mission_control.consumers import SSHConsumer

    c = SSHConsumer()
    c.channel_name = "test-channel"
    c.close = AsyncMock()
    c.accept = AsyncMock()
    c.send = AsyncMock()
    return c


def _scope(user, instance_uuid="test-uuid-1234"):
    return {
        "type": "websocket",
        "user": user,
        "url_route": {"kwargs": {"instance_uuid": instance_uuid}},
    }


@pytest.fixture
def unauthenticated_scope():
    """WebSocket scope with anonymous user."""
    return _scope(AnonymousUser())


@pytest.fixture
def real_user(db):
    return User.objects.create_user(username="ssh-consumer@example.com", email="ssh-consumer@example.com")


@pytest.fixture
def seeded_ssh_range(range_ssh_instance, real_user):
    """A real READY engine Range owned by ``real_user`` with one SSH instance."""
    _rng, instance = range_ssh_instance(real_user)
    return real_user, instance


class TestSSHConsumerConnectGuards:
    """Connect guards that reject before any range/SSH work (no DB)."""

    @pytest.mark.asyncio
    async def test_rejects_unauthenticated_user(self, consumer, unauthenticated_scope):
        """Unauthenticated users are rejected."""
        consumer.scope = unauthenticated_scope

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    @pytest.mark.asyncio
    async def test_rejects_missing_instance_uuid(self, consumer):
        """Missing instance_uuid returns INVALID_REQUEST."""
        user = MagicMock(is_authenticated=True)
        consumer.scope = {"type": "websocket", "user": user, "url_route": {"kwargs": {}}}

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)


@pytest.mark.django_db(transaction=True)
class TestSSHConsumerConnectRealRange:
    """Connect driven through the real engine.services.connect_terminal.

    Uses a real user + real READY Range; the SSH key is fetched over the boto3
    Secrets Manager boundary, and the asyncssh transport is the only thing
    mocked (and only for the success case — the failure case naturally fails on
    the opaque test key). The full ASGI-stack path is additionally covered by
    tests/integration/asgi/test_terminal_ws.py.
    """

    @pytest.mark.asyncio
    async def test_rejects_when_no_active_range(self, consumer, real_user):
        """No active range -> connect_terminal raises ValueError -> NOT_FOUND."""
        consumer.scope = _scope(real_user, "no-such-instance")

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    @pytest.mark.asyncio
    async def test_rejects_on_ssh_connection_failure(self, consumer, seeded_ssh_range, secrets_boundary):
        """A real SSH connect failure (opaque test key) returns SSH_CONNECTION_FAILED."""
        user, instance = seeded_ssh_range
        consumer.scope = _scope(user, instance["uuid"])

        with secrets_boundary():
            await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)

    @pytest.mark.asyncio
    async def test_connect_runs_on_dedicated_terminal_executor(self, consumer, seeded_ssh_range):
        """Terminal connect work runs on the terminal-connect pool, not the
        shared sync lane — the isolation that keeps a connect storm from
        blocking page renders (#929, WS-3).

        Observed at the boto3 Secrets Manager boundary: the SSH-key fetch that
        ``connect_terminal`` performs records the worker thread it ran on.
        """
        import threading

        user, instance = seeded_ssh_range
        captured: dict[str, str] = {}

        def record_thread(**_kwargs):
            captured["thread"] = threading.current_thread().name
            return {"SecretString": "TEST-SSH-PRIVATE-KEY-MATERIAL"}

        client = MagicMock()
        client.get_secret_value.side_effect = record_thread

        fake_conn = AsyncMock()
        consumer.scope = _scope(user, instance["uuid"])
        with (
            patch("boto3.client", return_value=client),
            patch("asyncssh.import_private_key", return_value=MagicMock()),
            patch("asyncssh.connect", new=AsyncMock(return_value=fake_conn)),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            await consumer.connect()

        assert captured["thread"].startswith("terminal-connect")

    @pytest.mark.asyncio
    async def test_rejects_when_terminal_executor_saturated(self, consumer, seeded_ssh_range):
        """A saturated terminal executor fails the connect fast with the
        retryable SERVICE_UNAVAILABLE close, instead of queuing unbounded work
        (#929). The session slot taken before the connect is released so the
        rejection self-heals.

        Drives the real bounded admission gate: every slot is drained so the
        consumer's genuine ``run_terminal_sync`` call is rejected — no internal
        patching, only observed close behavior.
        """
        from mission_control import terminal_executor

        user, instance = seeded_ssh_range
        consumer.scope = _scope(user, instance["uuid"])

        admission = terminal_executor._get_admission()
        drained = 0
        while admission.acquire(blocking=False):
            drained += 1
        try:
            await consumer.connect()
        finally:
            for _ in range(drained):
                admission.release()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SERVICE_UNAVAILABLE)
        assert consumer._session_acquired is False

    @pytest.mark.asyncio
    async def test_accepts_on_successful_connect(self, consumer, seeded_ssh_range, secrets_boundary):
        """Successful connection accepts the WebSocket and starts the read task."""
        user, instance = seeded_ssh_range
        consumer.scope = _scope(user, instance["uuid"])

        fake_conn = AsyncMock()  # asyncssh connection (boundary)
        with (
            secrets_boundary(),
            patch("asyncssh.import_private_key", return_value=MagicMock()),
            patch("asyncssh.connect", new=AsyncMock(return_value=fake_conn)),
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_create_task.return_value = MagicMock()
            await consumer.connect()

        consumer.accept.assert_awaited_once()
        mock_create_task.assert_called_once()


class TestSSHConsumerDisconnect:
    """Tests for disconnect() behavior."""

    @pytest.mark.asyncio
    async def test_cancels_read_task(self, consumer):
        """Disconnect cancels the background read task."""

        # Create a real task that we can cancel
        async def dummy_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_task())
        consumer._read_task = task

        await consumer.disconnect(close_code=1000)

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_closes_ssh_connection(self, consumer):
        """Disconnect closes the SSH connection."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.disconnect(close_code=1000)

        mock_ssh.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_disconnect_without_connect(self, consumer):
        """Disconnect with no SSH/session is a clean no-op.

        When connect never completed there is no SSH connection to tear down and
        no acquired session slot to release, so disconnect must complete without
        raising and without inventing teardown work.
        """
        consumer.ssh_conn = None
        consumer._read_task = None
        consumer._session_acquired = False
        consumer._user_id = None

        await consumer.disconnect(close_code=1000)

        # No SSH teardown attempted, and the session slot stays released.
        assert consumer.ssh_conn is None
        assert consumer._session_acquired is False

    @pytest.mark.asyncio
    async def test_disconnect_audit_carries_close_reason_and_email(self, consumer):
        """The disconnect audit event identifies the user and why the session ended.

        The bounded ``_close_reason`` (set by the read loop on timeout/EOF)
        appears in the audit context so a timeout is distinguishable from a plain
        close, and the user email is attached to the session row.
        """
        consumer._user_id = 7
        consumer._user_email = "operator@example.com"
        consumer._close_reason = "idle_timeout"
        consumer._audit_best_effort = AsyncMock()

        await consumer.disconnect(close_code=1000)

        consumer._audit_best_effort.assert_awaited_once()
        kwargs = consumer._audit_best_effort.await_args.kwargs
        assert kwargs["action"] == "disconnect"
        assert kwargs["session"].email == "operator@example.com"
        assert "idle_timeout" in kwargs["context"]


class TestSSHConsumerReceive:
    """Tests for receive() input handling."""

    @pytest.mark.asyncio
    async def test_forwards_input_to_ssh(self, consumer):
        """Input messages are forwarded to SSH connection."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.receive(text_data=json.dumps({"type": "input", "data": "ls -la\n"}))

        mock_ssh.send.assert_awaited_once_with(b"ls -la\n")

    @pytest.mark.asyncio
    async def test_handles_resize_message(self, consumer):
        """Resize messages update terminal dimensions."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh

        await consumer.receive(text_data=json.dumps({"type": "resize", "cols": 120, "rows": 40}))

        mock_ssh.resize.assert_awaited_once_with(120, 40)

    @pytest.mark.asyncio
    async def test_ignores_invalid_json(self, consumer):
        """Invalid JSON is ignored (logged as warning)."""
        mock_ssh = AsyncMock()
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer.receive(text_data="not json")

        mock_ssh.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ignores_when_no_ssh_connection(self, consumer):
        """Input before the SSH connection exists is dropped, not buffered.

        With no ``ssh_conn`` there is nothing to forward to, so receive must
        complete without raising and without emitting anything back to the
        WebSocket.
        """
        consumer.ssh_conn = None

        await consumer.receive(text_data=json.dumps({"type": "input", "data": "test"}))

        consumer.send.assert_not_awaited()


class TestSSHConsumerReadOutput:
    """Tests for _read_ssh_output() background task."""

    @pytest.mark.asyncio
    async def test_sends_output_to_websocket(self, consumer):
        """SSH output is sent to WebSocket as JSON."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive = AsyncMock(side_effect=[b"Hello World", None])
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        # Mock is_connected to return False after first iteration
        call_count = [0]

        def is_connected_side_effect():
            call_count[0] += 1
            return call_count[0] <= 1

        type(mock_ssh).is_connected = property(lambda self: is_connected_side_effect())

        await consumer._read_ssh_output()

        consumer.send.assert_awaited()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["type"] == "output"
        assert message["data"] == "Hello World"

    @pytest.mark.asyncio
    async def test_reraises_cancelled_error_after_cleanup(self, consumer):
        """CancelledError propagates (cancellation must not be swallowed), but
        cleanup still runs via the finally block."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive.side_effect = asyncio.CancelledError()
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        with pytest.raises(asyncio.CancelledError):
            await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_closes_websocket_on_error(self, consumer):
        """Other errors close the WebSocket."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive.side_effect = RuntimeError("Read failed")
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        consumer.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_sets_error_close_reason(self, consumer):
        """A read error records a bounded ``error`` close reason for audit."""
        mock_ssh = AsyncMock()
        mock_ssh.is_connected = True
        mock_ssh.receive.side_effect = RuntimeError("Read failed")
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        assert consumer._close_reason == "error"

    @pytest.mark.asyncio
    async def test_eof_sets_shell_eof_close_reason(self, consumer):
        """Shell EOF records a bounded ``shell_eof`` close reason."""
        mock_ssh = AsyncMock()
        mock_ssh.receive = AsyncMock(return_value=None)
        mock_ssh.at_eof = MagicMock(return_value=True)
        type(mock_ssh).is_connected = property(lambda self: True)
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        assert consumer._close_reason == "shell_eof"

    @pytest.mark.asyncio
    async def test_idle_timeout_sets_close_reason(self, consumer, settings):
        """An idle session past the idle limit records ``idle_timeout``."""
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0.01
        settings.TERMINAL_MAX_SESSION_SECONDS = 0
        settings.TERMINAL_READ_POLL_SECONDS = 0.05

        async def slow_receive(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return None

        mock_ssh = AsyncMock()
        mock_ssh.receive = slow_receive
        mock_ssh.at_eof = MagicMock(return_value=False)
        type(mock_ssh).is_connected = property(lambda self: True)
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        assert consumer._close_reason == "idle_timeout"

    @pytest.mark.asyncio
    async def test_max_duration_sets_close_reason(self, consumer, settings):
        """A session past the max-duration limit records ``max_duration``."""
        settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0
        settings.TERMINAL_MAX_SESSION_SECONDS = 0.01
        settings.TERMINAL_READ_POLL_SECONDS = 0.05

        async def slow_receive(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return None

        mock_ssh = AsyncMock()
        mock_ssh.receive = slow_receive
        mock_ssh.at_eof = MagicMock(return_value=False)
        type(mock_ssh).is_connected = property(lambda self: True)
        consumer.ssh_conn = mock_ssh
        consumer.instance_uuid = "test"

        await consumer._read_ssh_output()

        assert consumer._close_reason == "max_duration"
