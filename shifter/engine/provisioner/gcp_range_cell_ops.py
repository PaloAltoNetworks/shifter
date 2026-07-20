"""Compute Engine operation helpers for the GCE range-cell backend.

Waiting on and surfacing errors from Compute long-running operations, plus the
existence-tolerant get/delete helpers, factored out of ``gcp_range_cells`` so
that module stays focused on resource lifecycle. The wait helpers accept both
the google-cloud-compute SDK operation objects (which expose ``.result()``) and
the dict-shaped responses used in tests.
"""

from __future__ import annotations

import logging
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
