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
    """``-k uvicorn_worker.UvicornWorker`` must resolve at import time.

    ``entrypoint.sh`` passes ``-k uvicorn_worker.UvicornWorker`` to
    Gunicorn. If the symbol cannot be imported, the master exits
    before serving any HTTP or websocket traffic. The current Uvicorn
    docs mark the legacy ``uvicorn.workers`` submodule deprecated and
    direct users to the standalone ``uvicorn-worker`` distribution;
    this test pins that contract.
    """
    from uvicorn_worker import UvicornWorker

    assert UvicornWorker.__module__.startswith("uvicorn_worker")
