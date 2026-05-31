"""Asynchronous Guacamole URL bootstrap runner."""

from __future__ import annotations

import atexit
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import BoundedSemaphore
from uuid import UUID

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from mission_control.models import GuacamoleBootstrapRequest
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

_DEFAULT_WORKERS = 4
_DEFAULT_TTL_SECONDS = 300

_slot_limit: int | None = None
_slots: BoundedSemaphore | None = None
_executor: ThreadPoolExecutor | None = None


class BootstrapQueueFull(Exception):
    """Raised when Guacamole bootstrap workers are already occupied."""


class BootstrapFailure(Exception):
    """Raised by a bootstrap builder for an expected user-facing failure."""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = _normalise_status_code(status_code)


def _normalise_status_code(status_code: int) -> int:
    """Clamp persisted failure codes to HTTP error statuses."""
    if 400 <= status_code <= 599:
        return status_code
    return 500


def _clean_error_message(message: str) -> str:
    """Return a bounded single-line error string for polling clients."""
    cleaned = message.replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:500] or "Guacamole session bootstrap failed"


def _ttl_seconds() -> int:
    """Return the configured bootstrap record lifetime."""
    raw_value = int(getattr(settings, "GUACAMOLE_BOOTSTRAP_TTL_SECONDS", _DEFAULT_TTL_SECONDS))
    return max(30, raw_value)


def _worker_limit() -> int:
    """Return the configured per-process worker limit."""
    return max(1, int(getattr(settings, "GUACAMOLE_BOOTSTRAP_WORKERS", _DEFAULT_WORKERS)))


def _get_slots() -> BoundedSemaphore:
    """Return the semaphore that bounds in-process bootstrap concurrency."""
    global _slot_limit, _slots
    worker_limit = _worker_limit()
    if _slots is None or _slot_limit != worker_limit:
        _slot_limit = worker_limit
        _slots = BoundedSemaphore(worker_limit)
    return _slots


def _get_executor() -> ThreadPoolExecutor:
    """Return the lazily-created bootstrap worker pool."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_worker_limit(), thread_name_prefix="guacamole-bootstrap")
        atexit.register(_executor.shutdown, wait=False)
    return _executor


def _user_id_from_value(value: int | str) -> int:
    """Normalize Django user identifiers for storage."""
    return int(value)


def enqueue_guacamole_bootstrap(
    *,
    user_id: int | str,
    protocol: str,
    target_id: str,
    build_url: Callable[[], str],
) -> GuacamoleBootstrapRequest:
    """Create a bootstrap request and run the blocking token exchange off-path."""
    slots = _get_slots()
    if not slots.acquire(blocking=False):
        raise BootstrapQueueFull

    try:
        bootstrap = GuacamoleBootstrapRequest.objects.create(
            user_id=_user_id_from_value(user_id),
            protocol=protocol,
            target_id=str(target_id)[:200],
            status=GuacamoleBootstrapRequest.Status.PENDING,
            expires_at=timezone.now() + timedelta(seconds=_ttl_seconds()),
        )
    except Exception:
        slots.release()
        raise

    if getattr(settings, "GUACAMOLE_BOOTSTRAP_INLINE", False):
        _run_bootstrap(bootstrap.id, build_url, slots)
        bootstrap.refresh_from_db()
        return bootstrap

    try:
        _get_executor().submit(_run_bootstrap, bootstrap.id, build_url, slots)
    except Exception:
        slots.release()
        bootstrap.status = GuacamoleBootstrapRequest.Status.FAILED
        bootstrap.error_message = "Guacamole bootstrap workers unavailable"
        bootstrap.error_status_code = 503
        bootstrap.save(update_fields=("status", "error_message", "error_status_code", "updated_at"))
        raise
    return bootstrap


def _run_bootstrap(request_id: UUID, build_url: Callable[[], str], slots: BoundedSemaphore) -> None:
    """Run a single blocking Guacamole URL build and persist the result."""
    close_old_connections()
    started = time.perf_counter()
    try:
        bootstrap = GuacamoleBootstrapRequest.objects.get(pk=request_id)
        bootstrap.status = GuacamoleBootstrapRequest.Status.RUNNING
        bootstrap.save(update_fields=("status", "updated_at"))

        try:
            result_url = build_url()
        except BootstrapFailure as exc:
            _finish_failure(bootstrap, started, str(exc), exc.status_code)
            return
        except Exception:
            logger.exception("Guacamole bootstrap failed: request_id=%s", request_id)
            _finish_failure(bootstrap, started, "Guacamole session bootstrap failed", 500)
            return

        duration_ms = _duration_ms(started)
        bootstrap.status = GuacamoleBootstrapRequest.Status.SUCCEEDED
        bootstrap.result_url = result_url
        bootstrap.error_message = ""
        bootstrap.error_status_code = 500
        bootstrap.duration_ms = duration_ms
        bootstrap.save(
            update_fields=(
                "status",
                "result_url",
                "error_message",
                "error_status_code",
                "duration_ms",
                "updated_at",
            )
        )
        logger.info(
            "Guacamole bootstrap succeeded: request_id=%s protocol=%s target_id=%s duration_ms=%s",
            request_id,
            safe_log_value(bootstrap.protocol),
            safe_log_value(bootstrap.target_id),
            duration_ms,
        )
    except GuacamoleBootstrapRequest.DoesNotExist:
        logger.warning("Guacamole bootstrap request disappeared before execution: request_id=%s", request_id)
    finally:
        slots.release()
        close_old_connections()


def _finish_failure(
    bootstrap: GuacamoleBootstrapRequest,
    started: float,
    message: str,
    status_code: int,
) -> None:
    duration_ms = _duration_ms(started)
    bootstrap.status = GuacamoleBootstrapRequest.Status.FAILED
    bootstrap.error_message = _clean_error_message(message)
    bootstrap.error_status_code = _normalise_status_code(status_code)
    bootstrap.duration_ms = duration_ms
    bootstrap.save(update_fields=("status", "error_message", "error_status_code", "duration_ms", "updated_at"))
    logger.warning(
        "Guacamole bootstrap failed: request_id=%s protocol=%s target_id=%s duration_ms=%s status_code=%s",
        bootstrap.id,
        safe_log_value(bootstrap.protocol),
        safe_log_value(bootstrap.target_id),
        duration_ms,
        bootstrap.error_status_code,
    )


def _duration_ms(started: float) -> int:
    """Return elapsed milliseconds since a monotonic start time."""
    return max(0, int((time.perf_counter() - started) * 1000))
