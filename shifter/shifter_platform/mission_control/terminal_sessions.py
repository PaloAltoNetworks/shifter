"""Process-local capacity accounting for terminal SSH websocket sessions.

Browser terminals run inside the portal ASGI process (see
``mission_control.consumers.SSHConsumer``), so a burst of sessions or a
reconnect storm can exhaust the event loop, file descriptors, and SSH sockets.
The registry here caps concurrency before any expensive SSH work happens, so
rejected connections are cheap. Kept in its own module so the transport
consumer stays focused and under the file-length cap (issue #847).
"""

from __future__ import annotations

import asyncio


class TerminalSessionRegistry:
    """Track active terminal SSH sessions and enforce per-process caps.

    Counts are per process, which matches how the portal is deployed (the cap
    protects each ASGI process individually). Access is guarded by an asyncio
    lock so concurrent connects/disconnects account accurately.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._total = 0
        self._per_user: dict[int, int] = {}

    async def try_acquire(self, user_id: int, max_total: int, max_per_user: int) -> bool:
        """Reserve a session slot for ``user_id``; return False if a cap is hit.

        A ``max_*`` of <= 0 disables that individual limit.
        """
        async with self._lock:
            if max_total > 0 and self._total >= max_total:
                return False
            if max_per_user > 0 and self._per_user.get(user_id, 0) >= max_per_user:
                return False
            self._total += 1
            self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
            return True

    async def release(self, user_id: int) -> None:
        """Return a previously acquired slot for ``user_id``."""
        async with self._lock:
            if self._total > 0:
                self._total -= 1
            remaining = self._per_user.get(user_id, 0) - 1
            if remaining > 0:
                self._per_user[user_id] = remaining
            else:
                self._per_user.pop(user_id, None)

    def snapshot(self) -> dict[str, int]:
        """Aggregate counts for telemetry/logging (no per-user identifiers)."""
        return {"active_sessions": self._total, "distinct_users": len(self._per_user)}

    def reset(self) -> None:
        """Drop all accounting and return to an empty state.

        Intended for process-lifecycle resets and per-test isolation only:
        the caller must ensure no connect/disconnect accounting is in flight
        (for example, between tests, or before the ASGI process begins serving
        traffic). It intentionally bypasses the asyncio lock because there is
        nothing concurrent to guard against at those boundaries. Resetting the
        singleton in place keeps every alias of it (notably
        ``mission_control.consumers._session_registry``) pointing at the same
        object, which a fresh ``TerminalSessionRegistry()`` would silently
        decouple.
        """
        self._total = 0
        self._per_user.clear()


# One registry per portal ASGI process. The cap is intentionally process-local.
session_registry = TerminalSessionRegistry()
