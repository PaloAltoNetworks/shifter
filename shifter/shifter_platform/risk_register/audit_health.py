"""Process-local audit logging health state.

The durable audit store is still ``AuditLog``. This module only tracks whether
this worker has observed an audit persistence failure so machine-visible health
surfaces can report degraded audit behavior without exposing audit payloads.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone


@dataclass(frozen=True)
class AuditHealthSnapshot:
    """Immutable reading of this process's audit health state."""

    degraded: bool
    failure_count: int
    last_failure_at: datetime | None
    last_failure_reason: str | None


class AuditHealthState:
    """Thread-safe audit degradation state for one Python worker process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failure_count = 0
        self._last_failure_at: datetime | None = None
        self._last_failure_reason: str | None = None

    def mark_degraded(self, exc: BaseException) -> None:
        """Record a failed audit write using only a bounded exception class."""
        reason = type(exc).__name__[:100]
        with self._lock:
            self._failure_count += 1
            self._last_failure_at = timezone.now()
            self._last_failure_reason = reason

    def snapshot(self) -> AuditHealthSnapshot:
        with self._lock:
            return AuditHealthSnapshot(
                degraded=self._failure_count > 0,
                failure_count=self._failure_count,
                last_failure_at=self._last_failure_at,
                last_failure_reason=self._last_failure_reason,
            )

    def reset(self) -> None:
        """Reset state for tests; production recovers by replacing the worker."""
        with self._lock:
            self._failure_count = 0
            self._last_failure_at = None
            self._last_failure_reason = None


_audit_health = AuditHealthState()


def mark_audit_degraded(exc: BaseException) -> None:
    """Mark this worker's audit health degraded after an audit write failure."""
    _audit_health.mark_degraded(exc)


def get_audit_health_snapshot() -> AuditHealthSnapshot:
    """Return this worker's current audit health state."""
    return _audit_health.snapshot()


def reset_audit_health() -> None:
    """Clear process-local audit health state for isolated tests."""
    _audit_health.reset()
