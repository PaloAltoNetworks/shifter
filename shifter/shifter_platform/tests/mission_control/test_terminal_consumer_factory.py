"""SSHConsumer terminal-connection factory injection (issue #993).

Before #993 an *accepted* terminal session could not be exercised in a test
without a forbidden production change, because the consumer always constructed a
live ``asyncssh`` ``SSHConnection`` (see the scope note in
``tests/integration/asgi/test_terminal_ws.py``). The injectable
``connection_factory`` is that seam: a test supplies a fake transport through
``SSHConsumer.as_asgi(connection_factory=...)`` and the full
MC -> CMS workspace authorization -> Engine runtime authorization path still
runs for real (real READY ``Range``, real workspace membership, real SSH-key
fetch over the boto3 boundary). Only the terminal transport is faked.
"""

from __future__ import annotations

import json

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from mission_control.consumers import SSHConsumer

# transaction=True: the connect path runs DB + secret work on the dedicated
# terminal executor thread, so the rolled-back wrapping transaction a plain
# django_db mark installs is not visible there (mirrors the guacamole API suite).
pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

INSTANCE_UUID = "550e8400-e29b-41d4-a716-446655440000"


class FakeTerminal:
    """A fake :class:`shared.remote_access.TerminalConnection` for one session.

    Streams a single output chunk then reports EOF so the consumer's read loop
    delivers the output and closes deterministically without any real network.
    """

    def __init__(self) -> None:
        self._connected = False
        self._delivered = False
        self.sent: list[bytes] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive(self, timeout: float = 0.1) -> bytes:
        if not self._delivered:
            self._delivered = True
            return b"welcome\r\n"
        return b""

    def at_eof(self) -> bool:
        return self._delivered

    async def resize(self, cols: int, rows: int) -> None:  # pragma: no cover - unused here
        pass


@pytest.fixture
def user(db):
    return User.objects.create_user(username="term-factory@example.com", email="term-factory@example.com")


@pytest.fixture(autouse=True)
def _terminal_limits(settings):
    settings.TERMINAL_MAX_SESSIONS = 5
    settings.TERMINAL_MAX_SESSIONS_PER_USER = 5
    settings.TERMINAL_READ_POLL_SECONDS = 0.05
    settings.TERMINAL_IDLE_TIMEOUT_SECONDS = 0
    settings.TERMINAL_MAX_SESSION_SECONDS = 0
    settings.CLOUD_PROVIDER = "aws"


async def _communicator(user, factory, *, instance_uuid=INSTANCE_UUID):
    communicator = WebsocketCommunicator(
        SSHConsumer.as_asgi(connection_factory=factory),
        f"/ws/terminal/{instance_uuid}/",
    )
    communicator.scope["user"] = user
    communicator.scope["url_route"] = {"kwargs": {"instance_uuid": instance_uuid}}
    return communicator


@pytest.mark.asyncio
async def test_injected_factory_drives_an_accepted_session(user, range_ssh_instance, secrets_boundary):
    """A fake transport is accepted and its output reaches the browser socket.

    The fake is only reached after real workspace + runtime authorization on a
    real READY range, proving the seam does not bypass either gate.
    """
    captured: dict[str, object] = {}
    fake = FakeTerminal()

    def factory(**kwargs):
        captured.update(kwargs)
        return fake

    await database_sync_to_async(range_ssh_instance)(user, cloud_provider="aws")

    with secrets_boundary():
        communicator = await _communicator(user, factory)
        connected, _ = await communicator.connect()
        assert connected is True

        message = await communicator.receive_from()
        assert json.loads(message) == {"type": "output", "data": "welcome\r\n"}
        await communicator.disconnect()

    # The factory received the facts resolved by the real engine authorization.
    assert captured["host"] == "10.50.1.10"
    assert captured["username"] == "ubuntu"
    assert captured["port"] == 22
    assert captured["session_id"] == INSTANCE_UUID


@pytest.mark.asyncio
async def test_injected_factory_not_reached_when_authorization_fails(user):
    """No range exists, so authorization fails and the fake is never built."""
    called = False

    def factory(**_kwargs):
        nonlocal called
        called = True
        return FakeTerminal()

    communicator = await _communicator(user, factory)
    connected, _code = await communicator.connect()

    assert connected is False
    assert called is False
    await communicator.disconnect()
