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
