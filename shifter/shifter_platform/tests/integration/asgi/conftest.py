"""Shared fixtures for the real-stack ASGI/Channels integration suite (#924).

These tests drive the *real* ``config.asgi.application`` through
``channels.testing.WebsocketCommunicator`` — the full
``ProtocolTypeRouter`` -> ``AllowedHostsOriginValidator`` ->
``AuthMiddlewareStack`` -> ``URLRouter`` stack. The channel layer is never
mocked; authentication is via a real Django session cookie rather than
``scope["user"]`` injection. See
``docs/architecture/asgi-render-integration-preflight-924.md`` for the
binding guardrails.
"""

from __future__ import annotations

import contextlib
import os
import socket
from collections.abc import Iterator

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()

# Origin/Host that satisfy the default test ``ALLOWED_HOSTS``
# (``localhost,127.0.0.1``) so ``AllowedHostsOriginValidator`` admits the
# handshake and the inner consumer decides the outcome.
ALLOWED_ORIGIN = b"http://localhost"
ALLOWED_HOST = b"localhost"
DISALLOWED_ORIGIN = b"http://evil.example.com"


def _redis_endpoint() -> tuple[str, int]:
    return os.environ.get("REDIS_HOST", "localhost").strip() or "localhost", int(os.environ.get("REDIS_PORT", "6379"))


def _redis_reachable() -> bool:
    host, port = _redis_endpoint()
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@contextlib.contextmanager
def _swapped_channel_layers(settings, layers: dict) -> Iterator[None]:
    """Install ``layers`` as ``CHANNEL_LAYERS`` and rebuild the layer cache.

    Channels caches built backends on ``channel_layers.backends`` and reads
    ``settings.CHANNEL_LAYERS`` lazily, so a posture switch must clear that
    cache both on entry (so the consumer and publisher pick up the new
    backend) and on exit (so the next test rebuilds from the restored
    settings). The pytest-django ``settings`` fixture restores
    ``CHANNEL_LAYERS`` itself.
    """
    from channels.layers import channel_layers

    settings.CHANNEL_LAYERS = layers
    channel_layers.backends.clear()
    try:
        yield
    finally:
        channel_layers.backends.clear()


@pytest.fixture
def in_memory_channel_layer(settings) -> Iterator[None]:
    """Force the in-memory channel-layer posture for the test.

    Deterministic regardless of the ambient ``CHANNEL_LAYER_BACKEND`` env so
    the same test behaves identically in the in-memory and Redis CI steps.
    """
    layers = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    with _swapped_channel_layers(settings, layers):
        yield


@pytest.fixture
def redis_channel_layer(settings) -> Iterator[None]:
    """Force the Redis channel-layer posture, skipping when Redis is absent.

    The layer config is built through ``config._channels`` (the canonical
    parser) rather than a parallel fixture-local one, per the preflight.
    """
    if not _redis_reachable():
        pytest.skip("Redis not reachable for the redis-posture integration test")

    from config._channels import _build_channel_layers

    host, port = _redis_endpoint()
    layers = _build_channel_layers({"CHANNEL_LAYER_BACKEND": "redis", "REDIS_HOST": host, "REDIS_PORT": str(port)})
    with _swapped_channel_layers(settings, layers):
        yield


@pytest.fixture
def asgi_application():
    """The real composed ASGI application under test."""
    from config.asgi import application

    return application


def handshake_headers(cookie_value: str | None = None, *, origin: bytes = ALLOWED_ORIGIN) -> list[tuple[bytes, bytes]]:
    """Build websocket handshake headers (allowed Host, given Origin, opt cookie).

    A non-None ``cookie_value`` adds the ``sessionid`` cookie so
    ``AuthMiddlewareStack`` resolves ``scope["user"]`` from the real session
    rather than by injecting the user into the consumer scope.
    """
    headers = [(b"origin", origin), (b"host", ALLOWED_HOST)]
    if cookie_value:
        headers.append((b"cookie", f"sessionid={cookie_value}".encode()))
    return headers


def make_user(email: str) -> User:
    """Create an authenticated-capable user (call from sync setup / a thread)."""
    return User.objects.create_user(username=email, email=email, password="ws-pass-123")


def login_cookie(user) -> str:
    """Return the ``sessionid`` value for a real logged-in session (sync only).

    Must run outside the event loop (fixture setup or ``sync_to_async``); it
    writes the session row via the sync ORM.
    """
    client = Client()
    client.force_login(user)
    return client.cookies["sessionid"].value


@pytest.fixture
def ws_user(db):
    """A single authenticated-capable user, created during sync setup."""
    return make_user("ws-user@example.com")


@pytest.fixture
def ws_cookie_value(db, ws_user) -> str:
    """The ``sessionid`` for ``ws_user``, established during sync setup."""
    return login_cookie(ws_user)


@pytest.fixture
def ws_headers(ws_cookie_value) -> list[tuple[bytes, bytes]]:
    """Authenticated handshake headers (real session cookie, allowed Origin)."""
    return handshake_headers(ws_cookie_value)


@pytest.fixture
def anon_headers() -> list[tuple[bytes, bytes]]:
    """Allowed Origin/Host but no session cookie (anonymous handshake)."""
    return handshake_headers()


# Test notification types/topics registered for the notification-fan-out tests.
NOTIFICATION_TYPE = "test_type"
NOTIFICATION_TOPIC_PREFIX = "test."
NOTIFICATION_TOPIC = "test.fanout"
DENY_TYPE = "deny_type"
DENY_TOPIC_PREFIX = "deny."
DENY_TOPIC = "deny.blocked"


def make_notification(user, *, topic: str = NOTIFICATION_TOPIC, payload: dict | None = None):
    """Create an undelivered, unexpired notification row (sync ORM)."""
    from datetime import timedelta

    from django.utils import timezone

    from shared.models import WebSocketNotification

    return WebSocketNotification.objects.create(
        recipient=user,
        notification_type=NOTIFICATION_TYPE,
        topic=topic,
        payload=payload if payload is not None else {"msg": "hello"},
        expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.fixture
def registered_notification_type():
    """Register an allow-all and a deny-all test notification type.

    Snapshots and restores ``shared.notifications._registry`` rather than
    clearing it, so any notification types registered at app-init survive for
    other tests sharing the worker process. The deny type makes the
    unauthorized-subscription assertion deterministic regardless of which
    production types happen to be registered.
    """
    from shared import notifications as notif

    saved = dict(notif._registry)
    allow = notif.register_notification_type(
        name=NOTIFICATION_TYPE,
        topic_prefix=NOTIFICATION_TOPIC_PREFIX,
        can_subscribe=lambda _user, _topic: True,
        replace=True,
    )
    notif.register_notification_type(
        name=DENY_TYPE,
        topic_prefix=DENY_TOPIC_PREFIX,
        can_subscribe=lambda _user, _topic: False,
        replace=True,
    )
    try:
        yield allow
    finally:
        notif._registry.clear()
        notif._registry.update(saved)
