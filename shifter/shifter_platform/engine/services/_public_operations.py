"""Retry-safe public operation surface at the engine service boundary (#2086, ADR-063).

Re-exports the retry-binding primitives and the request -> operation-generation
lookup through ``engine.services`` so the CMS and presentation layers reach them
only via the public facade (ADR-001), never through the private
``engine.retry_binding`` module or the ORM directly.
"""

from __future__ import annotations

from uuid import UUID

from engine.retry_binding import (
    DEFAULT_RETRY_TTL_SECONDS,
    MintedOperation,
    RetryBindingResult,
    RetryKeyConflict,
    bind_public_operation,
    lookup_public_operation,
    prune_expired_retry_bindings,
)

__all__ = [
    "DEFAULT_RETRY_TTL_SECONDS",
    "MintedOperation",
    "RetryBindingResult",
    "RetryKeyConflict",
    "bind_public_operation",
    "lookup_public_operation",
    "operation_id_for_request",
    "prune_expired_retry_bindings",
]


def operation_id_for_request(request_id: str | UUID) -> str | None:
    """Return the current operation generation stamped on a request's range, if any."""
    from engine.models import Range

    row = Range.objects.filter(request__request_id=UUID(str(request_id))).only("provisioner_operation_id").first()
    if row is None or row.provisioner_operation_id is None:
        return None
    return str(row.provisioner_operation_id)
