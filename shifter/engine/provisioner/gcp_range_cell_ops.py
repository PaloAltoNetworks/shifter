"""Compute Engine operation helpers for the GCE range-cell backend.

Waiting on and surfacing errors from Compute long-running operations, plus the
existence-tolerant get/delete helpers, factored out of ``gcp_range_cells`` so
that module stays focused on resource lifecycle. The wait helpers accept both
the google-cloud-compute SDK operation objects (which expose ``.result()``) and
the dict-shaped responses used in tests.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable

from gcp_range_cell_clients import GCEClients, GoogleExceptions
from gcp_range_cell_types import RangeCellPlan
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

_OPERATION_TIMEOUT_SECONDS = 600


def _get_or_none(
    callable_obj: Callable[..., object],
    exceptions: GoogleExceptions,
    **kwargs: object,
) -> object | None:
    """Return a Compute resource or None when the provider reports NotFound."""
    try:
        return callable_obj(**kwargs)
    except exceptions.NotFound:
        return None


def _delete_resource(
    plan: RangeCellPlan,
    clients: GCEClients,
    getter: Callable[..., object],
    deleter: Callable[..., object],
    scope: str,
    **kwargs: object,
) -> None:
    """Delete a Compute resource when it exists."""
    name = str(next(reversed(kwargs.values())))
    existing = _get_or_none(getter, clients.google_exceptions, **kwargs)
    if existing is None:
        return
    operation = deleter(**kwargs)
    _wait_for_operation(plan, clients, operation, scope)
    logger.info("Deleted GCE range resource name_fp=%s", safe_log_fingerprint(name))


def _operation_name(operation: object) -> str:
    """Extract a Compute operation name from SDK or dict responses."""
    if isinstance(operation, dict):
        return str(operation.get("name", ""))
    return str(getattr(operation, "name", "") or "")


def _get_operation_field(operation: object, name: str) -> object | None:
    """Read an operation field from SDK or dict responses."""
    if isinstance(operation, dict):
        return operation.get(name)
    return getattr(operation, name, None)


def _operation_error_messages(operation: object) -> list[str]:
    """Extract provider error messages from a completed operation."""
    error = _get_operation_field(operation, "error")
    if not error:
        return []
    entries = error.get("errors") if isinstance(error, dict) else _get_operation_field(error, "errors")
    if not isinstance(entries, list):
        return [str(error)]
    messages: list[str] = []
    for entry in entries:
        code = _get_operation_field(entry, "code")
        message = _get_operation_field(entry, "message")
        if code and message:
            messages.append(f"{code}: {message}")
        elif message:
            messages.append(str(message))
        else:
            messages.append(str(entry))
    return messages


def _raise_for_operation_errors(operation: object, *, operation_name: str, scope: str) -> None:
    """Raise when Compute reports errors on a completed operation."""
    errors = _operation_error_messages(operation)
    if errors:
        detail = "; ".join(errors)
        raise RuntimeError(f"GCE {scope} operation {operation_name or '<unknown>'} failed: {detail}")


def _wait_for_operation(plan: RangeCellPlan, clients: GCEClients, operation: object, scope: str) -> None:
    """Wait for a Compute operation and surface asynchronous failures."""
    if operation is None:
        return
    result_method = getattr(operation, "result", None)
    if callable(result_method):
        result = result_method(timeout=_OPERATION_TIMEOUT_SECONDS)
        _raise_for_operation_errors(result or operation, operation_name=_operation_name(operation), scope=scope)
        return

    operation_name = _operation_name(operation)
    if not operation_name:
        _raise_for_operation_errors(operation, operation_name="", scope=scope)
        return

    result = None
    if scope == "global":
        result = clients.global_operations.wait(project=plan["project_id"], operation=operation_name)
    elif scope == "region":
        result = clients.region_operations.wait(
            project=plan["project_id"], region=plan["region"], operation=operation_name
        )
    elif scope == "zone":
        result = clients.zone_operations.wait(project=plan["project_id"], zone=plan["zone"], operation=operation_name)
    _raise_for_operation_errors(result or operation, operation_name=operation_name, scope=scope)


# GCE limits clone operations against one source machine image. A transient
# per-source 403 is not a permanent range failure; spread bounded retries so
# event-sized waves do not immediately collide again.
_MACHINE_IMAGE_RATE_RETRY_DELAYS = (15, 30, 60, 120, 180, 240)


def _machine_image_retry_jitter(name: str, attempt: int, delay: int) -> int:
    """Spread retries for one source image without exposing the instance name."""
    digest = hashlib.sha256(f"{name}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:2], "big") % (min(30, delay) + 1)


def insert_instance_with_machine_image_retry(
    plan: RangeCellPlan,
    clients: GCEClients,
    insert_request: dict[str, object],
    resource_name: str,
) -> object | None:
    """Insert a machine-image instance, retrying on Compute operation rate limits.

    Returns the instance a prior attempt already created when a rate-limited
    operation raced a successful one (the caller finalizes it); returns ``None``
    when this call performed the insert. Raises on non-rate-limit errors or once
    the bounded retries are exhausted.
    """
    for attempt in range(len(_MACHINE_IMAGE_RATE_RETRY_DELAYS) + 1):
        try:
            operation = clients.instances.insert(request=insert_request)
            _wait_for_operation(plan, clients, operation, "zone")
            return None
        except Exception as exc:
            if "RESOURCE_OPERATION_RATE_EXCEEDED" not in str(exc):
                raise
            # A failed operation can race a successful retry/observation. Re-read
            # the deterministic name before issuing another insert.
            existing = _get_or_none(
                clients.instances.get,
                clients.google_exceptions,
                project=plan["project_id"],
                zone=plan["zone"],
                instance=resource_name,
            )
            if existing is not None:
                return existing
            if attempt == len(_MACHINE_IMAGE_RATE_RETRY_DELAYS):
                raise
            delay = _MACHINE_IMAGE_RATE_RETRY_DELAYS[attempt]
            logger.warning(
                "GCE machine-image clone rate limited; retrying instance name_fp=%s attempt=%d",
                safe_log_fingerprint(resource_name),
                attempt + 1,
            )
            time.sleep(delay + _machine_image_retry_jitter(resource_name, attempt, delay))
    # The final attempt either returns or raises, so this is unreachable; it
    # exists only to satisfy the type checker for the loop's normal exit.
    return None
