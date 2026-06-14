"""Real-stack terminal websocket integration tests (#924, TEST-6).

These drive ``config.asgi.application`` end to end through
``WebsocketCommunicator`` — routing, ``AllowedHostsOriginValidator``,
``AuthMiddlewareStack``, and ``SSHConsumer`` — with a real session cookie and
the real ``mission_control.terminal_sessions.session_registry``. The channel
layer is never mocked.

Scope note (see the preflight doc): a fully *accepted* SSH session is not
exercised here. ``engine.services.get_ssh_connection_info`` hardcodes port 22
and resolves the host/key from a real range row, so an accepted interactive
session would need either a production change (forbidden for this
verification issue) or a loopback SSH server bound to a privileged port. The
connect-rejection, capacity, origin, and slot-accounting paths fully cover the
"connect / capacity / disconnect" acceptance criterion without mocking the
channel layer or patching ``SSHConsumer`` / ``connect_terminal`` /
``SSHConnection``.
"""

from __future__ import annotations

import uuid

import pytest
from channels.testing import WebsocketCommunicator

from mission_control.terminal_sessions import session_registry
from shared.enums import WebSocketCloseCode

TERMINAL_PATH = "/ws/terminal/{instance}/"


def _terminal_url() -> str:
    return TERMINAL_PATH.format(instance=uuid.uuid4().hex)


@pytest.mark.django_db(transaction=True)
class TestTerminalWebsocketRealStack:
    """SSHConsumer reached through the real composed ASGI application."""

    @pytest.mark.asyncio
    async def test_unauthenticated_connection_closed_not_authenticated(self, asgi_application, anon_headers):
        """An anonymous handshake is closed with NOT_AUTHENTICATED (4001)."""
        communicator = WebsocketCommunicator(asgi_application, _terminal_url(), headers=anon_headers)
        connected, code = await communicator.connect()

        assert connected is False
        assert code == WebSocketCloseCode.NOT_AUTHENTICATED
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_disallowed_origin_rejected_before_consumer(self, asgi_application, ws_cookie_value):
        """A cross-origin handshake is rejected by AllowedHostsOriginValidator.

        The validator wraps the terminal route, so even an authenticated user
        with a valid session is rejected before SSHConsumer runs.
        """
        from .conftest import DISALLOWED_ORIGIN, handshake_headers

        headers = handshake_headers(ws_cookie_value, origin=DISALLOWED_ORIGIN)
        communicator = WebsocketCommunicator(asgi_application, _terminal_url(), headers=headers)
        connected, code = await communicator.connect()

        assert connected is False
        # AllowedHostsOriginValidator denies the handshake itself with a plain
        # close (default code 1000), never reaching the consumer's explicit
        # auth close codes (e.g. 4001). The positive origin control lives in
        # the notification suite, where an authenticated allowed-origin connect
        # is accepted.
        assert code == 1000
        assert code != WebSocketCloseCode.NOT_AUTHENTICATED
        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_capacity_cap_rejects_when_saturated(self, asgi_application, ws_user, ws_headers, settings):
        """When the per-process session cap is full, connect → SERVICE_UNAVAILABLE."""
        settings.TERMINAL_MAX_SESSIONS = 1
        settings.TERMINAL_MAX_SESSIONS_PER_USER = 1

        # Saturate the single global slot so the consumer's pre-SSH cap check
        # rejects the new connection cheaply.
        acquired = await session_registry.try_acquire(ws_user.id, 1, 1)
        assert acquired
        try:
            communicator = WebsocketCommunicator(asgi_application, _terminal_url(), headers=ws_headers)
            connected, code = await communicator.connect()

            assert connected is False
            assert code == WebSocketCloseCode.SERVICE_UNAVAILABLE
            await communicator.disconnect()
        finally:
            await session_registry.release(ws_user.id)

    @pytest.mark.asyncio
    async def test_connect_storm_does_not_leak_session_slots(self, asgi_application, ws_user, ws_headers):
        """A burst of failing connects returns the registry to its baseline.

        Each authenticated connect acquires a session slot, then fails in
        ``SSHConsumer._open_ssh`` (no provisioned range for the instance) and
        must release the slot on the failure path. After the storm — including
        an abnormal client close — no slots may remain held.
        """
        baseline = session_registry.snapshot()["active_sessions"]

        for index in range(5):
            communicator = WebsocketCommunicator(asgi_application, _terminal_url(), headers=ws_headers)
            connected, _code = await communicator.connect()
            # The engine authorization / lookup runs for real and rejects the
            # connection; it must not be accepted.
            assert connected is False
            # Alternate a normal and an abnormal (1006) client disconnect.
            await communicator.disconnect(code=1006 if index % 2 else 1000)

        assert session_registry.snapshot()["active_sessions"] == baseline
