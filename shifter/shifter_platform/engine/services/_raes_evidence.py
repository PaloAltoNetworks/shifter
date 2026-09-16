"""Persist RAES provisioner operational evidence from outbox events (#1478).

The RAES-native provisioner emits ``range.raes.operation`` / ``range.raes.snapshot``
outbox events (it cannot import ``shared``). This engine consume-side maps them
onto the validated RAES sidecar persisters, so operation_status + runtime_snapshot
records land through the write-boundary redaction gate for the redacted Mission
Control reads. Range.status stays driven by the neutral range.status.updated flow;
these records are additive evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

# Shared event/payload keys, kept as constants so the same contract key is not
# repeated as a bare string literal across both record functions.
_KEY_OPERATION_ID = "operation_id"
_KEY_REQUEST_ID = "request_id"
_KEY_SOURCE_TIMESTAMP = "source_timestamp"


def _parse_timestamp(value: object) -> datetime:
    """Parse an ISO-8601 source timestamp from an event, defaulting to now."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Unparseable RAES event source_timestamp; using receipt time")
    return timezone.now()


def record_raes_operation_status(event: dict[str, Any]) -> None:
    """Persist an operation_status sidecar record from a range.raes.operation event."""
    request_id = event.get(_KEY_REQUEST_ID)
    operation_id = event.get(_KEY_OPERATION_ID)
    status = event.get("raes_status")
    if not (request_id and operation_id and status):
        logger.warning("Ignoring malformed RAES operation event event_id=%s", event.get("event_id", "unknown"))
        return
    source_timestamp = _parse_timestamp(event.get(_KEY_SOURCE_TIMESTAMP))
    payload: dict[str, Any] = {
        _KEY_OPERATION_ID: operation_id,
        _KEY_REQUEST_ID: str(request_id),
        "status": status,
        _KEY_SOURCE_TIMESTAMP: source_timestamp.isoformat(),
    }
    reason = event.get("status_reason")
    if reason:
        payload["status_reason"] = reason
    # Lazy import: shared.raes.operations pulls shared.models, which must not load
    # during Django app population (AppRegistryNotReady), matching _raes_range.
    from shared.raes.operations import persist_operation_status_record

    persist_operation_status_record(
        request_id=request_id,
        operation_id=operation_id,
        source_timestamp=source_timestamp,
        payload=payload,
    )


def record_raes_runtime_snapshot(event: dict[str, Any]) -> None:
    """Persist a runtime_snapshot sidecar record from a range.raes.snapshot event."""
    request_id = event.get(_KEY_REQUEST_ID)
    operation_id = event.get(_KEY_OPERATION_ID)
    resources = event.get("resources")
    if not (request_id and operation_id) or not isinstance(resources, list):
        logger.warning("Ignoring malformed RAES snapshot event event_id=%s", event.get("event_id", "unknown"))
        return
    source_timestamp = _parse_timestamp(event.get(_KEY_SOURCE_TIMESTAMP))
    payload: dict[str, Any] = {
        _KEY_OPERATION_ID: operation_id,
        _KEY_REQUEST_ID: str(request_id),
        "resources": resources,
        "captured_at": source_timestamp.isoformat(),
    }
    # Lazy import (see record_raes_operation_status for why).
    from shared.raes.operations import persist_runtime_snapshot_record

    # range_id on the record is an optional UUID projection key; the provisioner
    # event carries the integer range PK (not a UUID), and the MC RAES reads key on
    # request_id, so it is left unset rather than plumbing a UUID lookup here.
    persist_runtime_snapshot_record(
        request_id=request_id,
        operation_id=operation_id,
        source_timestamp=source_timestamp,
        payload=payload,
    )
