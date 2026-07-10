"""Durable event enqueueing for Shifter Engine provisioner.

Phase 1 (#476): events are written to the transactional outbox
(engine_range_event_outbox) via provisioner_db.enqueue_event_outbox instead of
being published directly to SNS.  A separate drainer (Phase 2) reads PENDING
rows and publishes them to the event bus.

Payloads are notification-shaped: IDs and status only, no secrets or full
instance state (see preflight note docs/architecture/range-event-delivery-preflight-476.md).

Usage from provisioner:
    from events import publish_status_update, publish_ready, publish_failed, publish_ngfw_event

    # When range status changes
    publish_status_update(
        request_id="uuid-string",
        range_id=1,
        user_id=42,
        new_status="provisioning",
    )

    # Atomic status + outbox (range_ops.py pattern):
    #   outbox_event = build_status_event(request_id, range_id, user_id, "paused")
    #   update_range_status(range_id, "paused", outbox_event=outbox_event)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from cyberscript.enums import ResourceStatus
from cyberscript.wire_constants import (
    EVENT_TYPE_CANCELLED,
    EVENT_TYPE_DESTROYED,
    EVENT_TYPE_NGFW,
    EVENT_TYPE_PROVISIONED,
    EVENT_TYPE_STATUS_UPDATED,
)

import provisioner_db
from log_redact import safe_log_fingerprint, safe_log_value

logger = logging.getLogger(__name__)

# Status string aliases for provisioner call sites (sourced from cyberscript.enums).
STATUS_PENDING = ResourceStatus.PENDING.value
STATUS_PROVISIONING = ResourceStatus.PROVISIONING.value
STATUS_READY = ResourceStatus.READY.value
STATUS_PAUSING = ResourceStatus.PAUSING.value
STATUS_PAUSED = ResourceStatus.PAUSED.value
STATUS_RESUMING = ResourceStatus.RESUMING.value
STATUS_FAILED = ResourceStatus.FAILED.value
STATUS_DESTROYING = ResourceStatus.DESTROYING.value
STATUS_DESTROYED = ResourceStatus.DESTROYED.value


def _get_sns_topic_arn() -> str:
    """Get event topic identifier from environment.

    Returns:
        Topic identifier for range events.

    Raises:
        ValueError: If no event topic identifier is set in environment.
    """
    topic_id = os.environ.get("RANGE_EVENTS_TOPIC_ID") or os.environ.get("SNS_RANGE_EVENTS_ARN")
    if not topic_id:
        raise ValueError("RANGE_EVENTS_TOPIC_ID/SNS_RANGE_EVENTS_ARN environment variable not set")
    return topic_id


def _create_event(
    event_type: str,
    request_id: str,
    range_id: int,
    user_id: int,
    **kwargs: str | int | None,
) -> dict[str, Any]:
    """Create a standard event envelope.

    Args:
        event_type: Type of event (e.g., "range.status.updated")
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
        **kwargs: Additional event-specific data

    Returns:
        Event dictionary ready for JSON serialization.
    """
    return {
        "event_type": event_type,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "range_id": range_id,
        "user_id": user_id,
        **kwargs,
    }


def _enqueue_event(event: dict[str, Any]) -> None:
    """Durably enqueue an event to the transactional outbox.

    Writes to engine_range_event_outbox in its own transaction.  A separate
    drainer (Phase 2) publishes PENDING rows to the event bus.

    Unlike the old _publish_event, failures are NOT swallowed: a DB error
    raises so the provisioner learns the event was not durably recorded.

    Args:
        event: Event dictionary containing at minimum ``event_id`` and
               ``event_type``.  Payload must be notification-shaped (IDs
               only, no secrets or full instance state).

    Raises:
        Exception: Any error from enqueue_event_outbox propagates to the caller.
    """
    provisioner_db.enqueue_event_outbox(event)
    logger.debug(
        "Enqueued event to outbox: request_id_fp=%s range_id_fp=%s event_type=%s",
        safe_log_fingerprint(event.get("request_id")),
        safe_log_fingerprint(event.get("range_id")),
        safe_log_value(event.get("event_type")),
    )


# Thin backward-compatibility alias.  External callers that imported
# _publish_event by name continue to work; new code should call _enqueue_event.
_publish_event = _enqueue_event


def build_status_event(
    request_id: str,
    range_id: int,
    user_id: int,
    new_status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Build a range.status.updated event dict without enqueueing it.

    Used by range_ops.py call sites that pass the event as ``outbox_event=``
    to update_range_status so the status change and event intent commit
    atomically in the same DB transaction.

    Args:
        request_id:    UUID string of the Request.
        range_id:      ID of the range.
        user_id:       ID of the user who owns the range.
        new_status:    New status value.
        error_message: Optional error message for failure events.

    Returns:
        Event dict ready to pass as outbox_event= to update_range_status.
    """
    return _create_event(
        event_type=EVENT_TYPE_STATUS_UPDATED,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=new_status,
        error_message=error_message,
    )


def publish_status_update(
    request_id: str,
    range_id: int,
    user_id: int,
    new_status: str,
    error_message: str | None = None,
) -> None:
    """Publish a status change event.

    Args:
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
        new_status: New status value
        error_message: Optional error message for failure events
    """
    event = _create_event(
        event_type=EVENT_TYPE_STATUS_UPDATED,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=new_status,
        error_message=error_message,
    )

    logger.info(
        "Publishing status update: request_id_fp=%s range_id_fp=%s new_status=%s",
        safe_log_fingerprint(request_id),
        safe_log_fingerprint(range_id),
        safe_log_value(new_status),
    )

    _enqueue_event(event)


def publish_ready(
    request_id: str,
    range_id: int,
    user_id: int,
) -> None:
    """Publish a provisioning complete event.

    This is a notification-only event. All state (instance IPs, subnet IDs, etc.)
    is written directly to the database by the provisioner before this event is
    published. Consumers should query the database if they need state details.

    Args:
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
    """
    # First publish status update
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_READY,
    )

    # Then publish provisioned event (notification only - no state data)
    event = _create_event(
        event_type=EVENT_TYPE_PROVISIONED,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info(
        "Publishing ready event: request_id_fp=%s range_id_fp=%s",
        safe_log_fingerprint(request_id),
        safe_log_fingerprint(range_id),
    )

    _enqueue_event(event)


def publish_failed(
    request_id: str,
    range_id: int,
    user_id: int,
    error_message: str,
) -> None:
    """Publish a provisioning failure event.

    Args:
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
        error_message: Description of the failure
    """
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_FAILED,
        error_message=error_message,
    )


def publish_destroyed(request_id: str, range_id: int, user_id: int) -> None:
    """Publish a range destroyed event.

    Args:
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
    """
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_DESTROYED,
    )

    event = _create_event(
        event_type=EVENT_TYPE_DESTROYED,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info(
        "Publishing destroyed event: request_id_fp=%s range_id_fp=%s",
        safe_log_fingerprint(request_id),
        safe_log_fingerprint(range_id),
    )

    _enqueue_event(event)


def publish_cancelled(request_id: str, range_id: int, user_id: int) -> None:
    """Publish a range cancelled event.

    Args:
        request_id: UUID string of the Request (primary correlation key)
        range_id: ID of the range
        user_id: ID of the user who owns the range
    """
    event = _create_event(
        event_type=EVENT_TYPE_CANCELLED,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info(
        "Publishing cancelled event: request_id_fp=%s range_id_fp=%s",
        safe_log_fingerprint(request_id),
        safe_log_fingerprint(range_id),
    )

    _enqueue_event(event)


# =============================================================================
# NGFW Event Publishing Functions
# =============================================================================


def publish_ngfw_event(
    request_id: str,
    instance_id: str,
    app_id: str | None,
    status: str,
    serial_number: str | None = None,
) -> None:
    """Publish a lightweight NGFW lifecycle notification.

    This is a notification-only event. All state is written directly to the
    database by the provisioner. Consumers should query the database if they
    need full state details.

    Args:
        request_id: UUID of the provisioning request (RequestSpec.id)
        instance_id: UUID of the instantiation (Instantiation.id)
        app_id: UUID of the CMS app (NGFW.app_id), or None if not yet associated
        status: ResourceStatus value (e.g., "provisioning", "ready", "failed", "destroyed")
        serial_number: PAN-OS serial number (included in "ready" events for CSP registration)
    """
    event = {
        "event_type": EVENT_TYPE_NGFW,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "instance_id": instance_id,
        "app_id": app_id,
        "status": status,
    }

    # Include serial_number only when provided (typically on "ready" events)
    if serial_number:
        event["serial_number"] = serial_number

    logger.info(
        "Publishing NGFW event: request_id_fp=%s instance_id_fp=%s app_id_fp=%s status=%s serial_fp=%s",
        safe_log_fingerprint(request_id),
        safe_log_fingerprint(instance_id),
        safe_log_fingerprint(app_id),
        safe_log_value(status),
        safe_log_fingerprint(serial_number) if serial_number else "<none>",
    )

    _enqueue_event(event)
