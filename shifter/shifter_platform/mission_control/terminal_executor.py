"""Dedicated executor for blocking terminal-websocket sync work.

The SSH terminal consumer runs blocking work — ``connect_terminal`` (a DB lookup
plus a Secrets Manager fetch) and audit writes — via ``sync_to_async``. By
default ``sync_to_async`` is *thread-sensitive*: it runs on the single shared
executor that also serves every synchronous Django request (page renders) on an
ASGI worker. A terminal connect storm therefore head-of-line-blocks page renders
on the same worker (#929, WS-3).

This module provides a bounded, terminal-owned ``ThreadPoolExecutor`` plus a
DB-hygiene wrapper, and an ``async`` helper that dispatches a blocking callable
onto that pool (``thread_sensitive=False``) so terminal sync work is isolated
from HTTP request handling. The pool mirrors the Guacamole bootstrap pool:
module-global, lazily created, shut down at process exit.

``ThreadPoolExecutor(max_workers=...)`` bounds only *concurrent* workers; its
internal submission queue is unbounded, so under a connect storm arbitrary
pending DB/Secrets/audit work could still accumulate in-process even though the
session cap rejects new sockets. ``run_terminal_sync`` therefore admits work
through a bounded counting gate (``_admission``) sized at workers plus a small
queue allowance: a saturated gate raises ``TerminalExecutorSaturated`` instead
of enqueuing, so the caller fails fast and surfaces the existing retryable
``SERVICE_UNAVAILABLE`` terminal close rather than letting work pile up.
"""

from __future__ import annotations

import atexit
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections

_DEFAULT_WORKERS = 8
_DEFAULT_QUEUE_SLACK = 16
_executor: ThreadPoolExecutor | None = None
_admission: threading.BoundedSemaphore | None = None
_admission_capacity: int | None = None
_lock = threading.Lock()


class TerminalExecutorSaturated(RuntimeError):
    """Raised when the terminal executor's admission gate is full.

    Signals that the per-process terminal-connect lane is saturated and the
    caller should fail fast (rejecting the connect with a retryable close code)
    rather than enqueue unbounded blocking work.
    """


def _worker_limit() -> int:
    """Return the configured per-process terminal-executor worker limit."""
    return max(1, int(getattr(settings, "TERMINAL_CONNECT_EXECUTOR_WORKERS", _DEFAULT_WORKERS)))


def _queue_slack() -> int:
    """Return the configured queued-task allowance above the worker limit."""
    return max(0, int(getattr(settings, "TERMINAL_CONNECT_EXECUTOR_QUEUE_SLACK", _DEFAULT_QUEUE_SLACK)))


def get_terminal_executor() -> ThreadPoolExecutor:
    """Return the lazily-created, bounded terminal-connect worker pool."""
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=_worker_limit(), thread_name_prefix="terminal-connect")
                atexit.register(_executor.shutdown, wait=False)
    return _executor


def _get_admission() -> threading.BoundedSemaphore:
    """Return the lazily-created admission gate bounding admitted work.

    Capacity is workers + queue slack: enough to keep every pool thread busy
    plus a small backlog, but finite so a connect storm is rejected instead of
    queued without limit.
    """
    global _admission, _admission_capacity
    if _admission is None:
        with _lock:
            if _admission is None:
                _admission_capacity = _worker_limit() + _queue_slack()
                _admission = threading.BoundedSemaphore(_admission_capacity)
    return _admission


def run_with_db_cleanup[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a blocking callable with per-thread Django DB hygiene.

    A long-lived pool thread must not reuse a stale/closed DB connection, so old
    connections are reaped before and after the call (the same discipline the
    Guacamole bootstrap worker uses).
    """
    close_old_connections()
    try:
        return fn(*args, **kwargs)
    finally:
        close_old_connections()


async def run_terminal_sync[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Await a blocking callable on the dedicated terminal-connect executor.

    ``thread_sensitive=False`` with an explicit executor keeps this work off the
    shared page-render sync lane. Admission is bounded: if the gate is already
    full (every worker busy and the queue allowance exhausted) this raises
    ``TerminalExecutorSaturated`` immediately instead of enqueuing unbounded
    work, so a connect storm fails fast rather than accumulating in-process.
    """
    admission = _get_admission()
    if not admission.acquire(blocking=False):
        raise TerminalExecutorSaturated("terminal-connect executor saturated")
    runner = sync_to_async(run_with_db_cleanup, thread_sensitive=False, executor=get_terminal_executor())
    try:
        return await runner(fn, *args, **kwargs)
    finally:
        admission.release()
