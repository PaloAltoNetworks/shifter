"""Terminal WebSocket capacity controls for the Shifter platform (issue #847).

Split out of ``config.settings`` to keep that module under Sonar S104's
500-line cap. Star-imported back into ``config.settings`` so the ``TERMINAL_*``
names resolve on ``config.settings`` exactly as before. See
docs/architecture/terminal-websocket-capacity-847.md.
"""

from __future__ import annotations

import os

__all__ = [
    "TERMINAL_CONNECT_EXECUTOR_QUEUE_SLACK",
    "TERMINAL_CONNECT_EXECUTOR_WORKERS",
    "TERMINAL_IDLE_TIMEOUT_SECONDS",
    "TERMINAL_MAX_SESSIONS",
    "TERMINAL_MAX_SESSIONS_PER_USER",
    "TERMINAL_MAX_SESSION_SECONDS",
    "TERMINAL_READ_POLL_SECONDS",
]


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``.

    An empty/unset value uses the default; a non-integer value is a
    configuration error and fails loud rather than silently degrading.
    Redefined here rather than imported from ``config.settings`` because
    ``settings`` imports this module -- importing back would be circular.
    Mirrors ``config.settings._env_int``.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


# ------------------------------------------------------------------------------
# Terminal WebSocket capacity controls (issue #847)
# ------------------------------------------------------------------------------
# Browser SSH terminals run inside the portal ASGI process: each active session
# holds a websocket FD, an SSH socket, asyncssh connection/process state, and a
# read task. During a live event a burst of sessions (or a reconnect storm) can
# saturate the event loop and exhaust file descriptors, making the whole portal
# look unreliable. These bounds cap concurrency and reclaim idle/abandoned
# sessions. A value <= 0 disables that individual limit.
#
# The caps are PER WORKER PROCESS. The production portal runs Gunicorn with
# PORTAL_WEB_WORKERS Uvicorn workers (entrypoint.sh, #174), and the
# TerminalSessionRegistry is process-local (one registry per worker), so the
# real per-instance ceiling is PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS and the
# per-user worst case is PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS_PER_USER.
# These knobs and PORTAL_WEB_WORKERS are wired through SSM/tfvars (#930), so an
# operator can retune them on a running instance without an image rebuild
# (update the parameter, then converge/restart the container).
#
# TERMINAL_READ_POLL_SECONDS is how often an idle session's read loop wakes to
# enforce the timeouts; it does NOT add latency to terminal output (output is
# delivered as soon as it arrives). The previous hard-coded 0.1s poll woke every
# idle terminal ~10x/second; a multi-second interval cuts idle CPU by orders of
# magnitude. See docs/architecture/terminal-websocket-capacity-847.md.
TERMINAL_MAX_SESSIONS = _env_int("TERMINAL_MAX_SESSIONS", 200)
TERMINAL_MAX_SESSIONS_PER_USER = _env_int("TERMINAL_MAX_SESSIONS_PER_USER", 10)
TERMINAL_IDLE_TIMEOUT_SECONDS = _env_int("TERMINAL_IDLE_TIMEOUT_SECONDS", 1800)
TERMINAL_MAX_SESSION_SECONDS = _env_int("TERMINAL_MAX_SESSION_SECONDS", 28800)
TERMINAL_READ_POLL_SECONDS = _env_int("TERMINAL_READ_POLL_SECONDS", 30)
# Bounded executor that runs blocking terminal-connect work (SSH connect, audit
# writes, ownership lookups) off the default thread-sensitive sync_to_async lane
# that serves HTTP page renders, so a terminal connect storm cannot head-of-line
# block page renders on the same ASGI worker (#929). Per-process, like the caps
# above.
TERMINAL_CONNECT_EXECUTOR_WORKERS = _env_int("TERMINAL_CONNECT_EXECUTOR_WORKERS", 8)
# Bounded admission gate on top of the terminal executor. ThreadPoolExecutor
# caps concurrent workers but has an unbounded submission queue, so a connect
# storm could still pile arbitrary blocking work in-process. Admission capacity
# is workers + this slack; once it is exhausted run_terminal_sync rejects with
# TerminalExecutorSaturated and the connect is closed with SERVICE_UNAVAILABLE
# (4503, retryable) instead of being queued without limit (#929).
TERMINAL_CONNECT_EXECUTOR_QUEUE_SLACK = _env_int("TERMINAL_CONNECT_EXECUTOR_QUEUE_SLACK", 16)
