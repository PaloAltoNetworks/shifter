"""Tests for the dedicated terminal-connect executor (#929, WS-3)."""

import threading

import pytest

from mission_control import terminal_executor


class TestTerminalExecutor:
    # run_with_db_cleanup / run_terminal_sync call close_old_connections(), which
    # touches the DB connection registry — allow DB access for the whole class.
    pytestmark = pytest.mark.django_db

    def test_executor_is_singleton_with_named_threads(self):
        from mission_control.terminal_executor import get_terminal_executor

        first = get_terminal_executor()
        second = get_terminal_executor()

        assert first is second
        assert first._thread_name_prefix == "terminal-connect"

    def test_run_with_db_cleanup_returns_callable_result(self):
        from mission_control.terminal_executor import run_with_db_cleanup

        result = run_with_db_cleanup(lambda value: value + 1, 41)

        assert result == 42

    def test_run_with_db_cleanup_propagates_errors(self):
        from mission_control.terminal_executor import run_with_db_cleanup

        def boom() -> None:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            run_with_db_cleanup(boom)

    @pytest.mark.asyncio
    async def test_run_terminal_sync_runs_on_terminal_pool(self):
        from mission_control.terminal_executor import run_terminal_sync

        captured: dict[str, str] = {}

        def work() -> str:
            captured["thread"] = threading.current_thread().name
            return "ok"

        result = await run_terminal_sync(work)

        assert result == "ok"
        assert captured["thread"].startswith("terminal-connect")

    @pytest.mark.asyncio
    async def test_run_terminal_sync_releases_admission_slot(self):
        """A completed task returns its admission slot so the gate does not leak."""
        from mission_control.terminal_executor import run_terminal_sync

        admission = terminal_executor._get_admission()
        before = admission._value  # type: ignore[attr-defined]

        await run_terminal_sync(lambda: "ok")

        assert admission._value == before  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_run_terminal_sync_rejects_when_admission_exhausted(self):
        """A full admission gate fails fast instead of enqueuing unbounded work."""
        from mission_control.terminal_executor import (
            TerminalExecutorSaturated,
            run_terminal_sync,
        )

        admission = terminal_executor._get_admission()
        # Drain every admission slot so the next submission cannot be admitted.
        drained = 0
        while admission.acquire(blocking=False):
            drained += 1
        try:
            assert drained > 0
            with pytest.raises(TerminalExecutorSaturated):
                await run_terminal_sync(lambda: "should-not-run")
        finally:
            for _ in range(drained):
                admission.release()

    @pytest.mark.asyncio
    async def test_run_terminal_sync_releases_slot_on_error(self):
        """An admission slot is returned even when the wrapped callable raises."""
        from mission_control.terminal_executor import run_terminal_sync

        admission = terminal_executor._get_admission()
        before = admission._value  # type: ignore[attr-defined]

        def boom() -> None:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            await run_terminal_sync(boom)

        assert admission._value == before  # type: ignore[attr-defined]
