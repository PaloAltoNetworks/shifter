"""Smoke test: confirm the Gunicorn worker class string boots.

The portal's production process manager switched from a single Daphne
process to Gunicorn with Uvicorn workers in issue #174. Gunicorn
imports the worker class via ``importlib`` at master boot, so a
dependency drift (missing ``uvicorn-worker`` package, deprecated
``uvicorn.workers`` import path) fails only when the container
starts. Asserting the import inside pytest surfaces the same failure
in CI and pre-commit, before the container ever boots.
"""

from __future__ import annotations

import importlib.util

import pytest


def test_uvicorn_has_a_websocket_backend() -> None:
    """A uvicorn-compatible WebSocket backend must be installed.

    ``entrypoint.sh`` serves the portal with Gunicorn/Uvicorn workers, and the
    portal's primary workload (terminal SSH, range-status, notification sockets)
    is WebSocket traffic. Uvicorn can only accept WebSocket upgrades when one of
    ``websockets`` / ``wsproto`` is importable; otherwise it logs "No supported
    WebSocket library detected" and the upgrade falls through to the HTTP app
    (a 301) while ``/health`` still returns 200 - a container-only regression
    invisible to the channels in-memory test client. ``test_uvicorn_worker_class``
    pins the worker *class*; this pins the protocol *backend* it depends on.
    """
    assert importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto"), (
        "uvicorn needs 'websockets' (or 'wsproto') installed to serve WebSockets"
    )


def test_uvicorn_worker_class_importable() -> None:
    """The standalone ``uvicorn_worker.UvicornWorker`` base must resolve at import time.

    ``entrypoint.sh`` serves the portal with
    ``config.asgi_worker.ShifterUvicornWorker``, which subclasses
    ``uvicorn_worker.UvicornWorker``; if the base symbol cannot be imported the
    Gunicorn master exits before serving any HTTP or websocket traffic. The
    current Uvicorn docs mark the legacy ``uvicorn.workers`` submodule
    deprecated and direct users to the standalone ``uvicorn-worker``
    distribution; this test pins that contract.
    """
    from uvicorn_worker import UvicornWorker

    assert UvicornWorker.__module__.startswith("uvicorn_worker")


def test_shifter_worker_pins_websocket_keepalive() -> None:
    """The deployed worker class must pin an explicit WebSocket keepalive (#931).

    ``entrypoint.sh`` serves the portal with ``config.asgi_worker.ShifterUvicornWorker``
    rather than the bare ``uvicorn_worker.UvicornWorker`` so the ALB never silently
    reaps an otherwise-idle terminal/notification/RDP WebSocket: Uvicorn sends
    protocol PING frames at ``ws_ping_interval`` < the ALB ``idle_timeout``. The
    preflight (docs/architecture/aws-long-lived-connection-drain-preflight-931.md)
    forbids assuming Uvicorn's default ping is active in the built Gunicorn worker
    path, so the interval/timeout are pinned in ``CONFIG_KWARGS`` and this test
    fails closed if they ever drop out.
    """
    from uvicorn_worker import UvicornWorker

    from config.asgi_worker import ShifterUvicornWorker

    assert issubclass(ShifterUvicornWorker, UvicornWorker)

    kwargs = ShifterUvicornWorker.CONFIG_KWARGS
    assert isinstance(kwargs.get("ws_ping_interval"), (int, float))
    assert kwargs["ws_ping_interval"] > 0
    assert isinstance(kwargs.get("ws_ping_timeout"), (int, float))
    assert kwargs["ws_ping_timeout"] > 0


_PING_ENV = "PORTAL_WEB_WS_PING_INTERVAL"


def test_keepalive_env_falls_back_to_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset (or blank) keepalive variable yields the supplied default."""
    from config.asgi_worker import _positive_float_env

    monkeypatch.delenv(_PING_ENV, raising=False)
    assert _positive_float_env(_PING_ENV, 20.0) == 20.0

    monkeypatch.setenv(_PING_ENV, "   ")
    assert _positive_float_env(_PING_ENV, 20.0) == 20.0


def test_keepalive_env_parses_a_valid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A positive numeric override is parsed and returned as a float."""
    from config.asgi_worker import _positive_float_env

    monkeypatch.setenv(_PING_ENV, "12.5")
    assert _positive_float_env(_PING_ENV, 20.0) == 12.5


def test_keepalive_env_rejects_non_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric value fails loud so the Gunicorn master aborts at boot."""
    from config.asgi_worker import _positive_float_env

    monkeypatch.setenv(_PING_ENV, "soon")
    with pytest.raises(ValueError, match="must be a number"):
        _positive_float_env(_PING_ENV, 20.0)


@pytest.mark.parametrize("bad_value", ["0", "-5"])
def test_keepalive_env_rejects_non_positive(monkeypatch: pytest.MonkeyPatch, bad_value: str) -> None:
    """A zero or negative interval would disable the keepalive; reject it."""
    from config.asgi_worker import _positive_float_env

    monkeypatch.setenv(_PING_ENV, bad_value)
    with pytest.raises(ValueError, match="positive number"):
        _positive_float_env(_PING_ENV, 20.0)
