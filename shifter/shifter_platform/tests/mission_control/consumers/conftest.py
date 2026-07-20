"""Pytest fixtures for WebSocket consumer tests."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_terminal_session_registry():
    """Keep the process-global terminal session registry isolated per test.

    ``SSHConsumer.connect()`` reserves a slot in the canonical
    ``mission_control.terminal_sessions.session_registry`` (the consumer reads
    it via the ``mission_control.consumers._session_registry`` alias). Some
    consumer tests drive the consumer with mocked WebSocket I/O and don't fully
    release the slot, which otherwise leaks reservations into later tests and
    into other suites that read the same global registry — notably the ASGI
    terminal integration tests (``tests/integration/asgi/test_terminal_ws.py``),
    which import ``session_registry`` directly. The leak only surfaces when
    pytest-xdist's ``loadscope`` happens to co-locate those modules on one
    worker, making it intermittent and order-dependent.

    Resetting the canonical registry's counters (and re-pointing the alias at
    it) around every consumer test makes the suite self-isolating regardless of
    worker scheduling.
    """
    from mission_control import consumers
    from mission_control.terminal_sessions import session_registry

    def _reset() -> None:
        consumers._session_registry = session_registry
        session_registry._total = 0
        session_registry._per_user.clear()

    _reset()
    yield
    _reset()
