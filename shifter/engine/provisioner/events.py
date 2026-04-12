"""Event publishing for Shifter Engine provisioner.

This module handles publishing range and NGFW status events to SNS for fan-out
via SQS queues.

Usage from provisioner:
    from events import publish_status_update, publish_ready, publish_failed, publish_ngfw_event

    # When range status changes
    publish_status_update(
        request_id="uuid-string",
        range_id=1,
        user_id=42,
        new_status="provisioning",
    )

    # When range provisioning completes (notification only - state written to DB first)
    publish_ready(
        request_id="uuid-string",
        range_id=1,
        user_id=42,
    )

    # When range provisioning fails
    publish_failed(
        request_id="uuid-string",
        range_id=1,
        user_id=42,
        error_message="Subnet exhausted",
    )

    # When NGFW lifecycle changes (status update, provisioned, failed, destroyed)
    publish_ngfw_event(
        request_id="uuid-string",
        instance_id="uuid-string",
        app_id="uuid-string",
        status="provisioning",  # Optional: ResourceStatus value
        state={"error_message": "..."},  # Optional: context-specific data
    )
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from cloud import get_event_bus

logger = logging.getLogger(__name__)

# TODO: #641 shared package
# Resource event type constants (matching shared.messages.events)
EVENT_TYPE_STATUS_UPDATED = "range.status.updated"
EVENT_TYPE_PROVISIONED = "range.provisioned"
EVENT_TYPE_DESTROYED = "range.destroyed"
EVENT_TYPE_CANCELLED = "range.cancelled"

# NGFW event type constant (matching shared.messages.events)
EVENT_TYPE_NGFW = "ngfw.event"

# Resource status constants (matching shared.enums.ResourceStatus)
STATUS_PENDING = "pending"
STATUS_PROVISIONING = "provisioning"
STATUS_READY = "ready"
STATUS_PAUSING = "pausing"
STATUS_PAUSED = "paused"
STATUS_RESUMING = "resuming"
STATUS_FAILED = "failed"
STATUS_DESTROYING = "destroying"
STATUS_DESTROYED = "destroyed"


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


def _publish_event(event: dict[str, Any]) -> None:
    """Publish event to SNS topic.

    Publishes the event to SNS
    via SQS queues.

    Args:
        event: Event dictionary to publish.
    """
    try:
        topic_arn = _get_sns_topic_arn()
        bus = get_event_bus()
        bus.publish(
            topic_id=topic_arn,
            message=json.dumps(event),
            attributes={"event_type": event.get("event_type", "unknown")},
        )

        logger.debug(
            "Published event: request_id=%s range_id=%s event_type=%s",
            event.get("request_id"),
            event.get("range_id"),
            event.get("event_type"),
        )

    except Exception as e:
        logger.error(
            "Failed to publish event: request_id=%s range_id=%s error=%s",
            event.get("request_id"),
            event.get("range_id"),
            str(e),
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
        "Publishing status update: request_id=%s range_id=%s new_status=%s",
        request_id,
        range_id,
        new_status,
    )

    _publish_event(event)


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
        "Publishing ready event: request_id=%s range_id=%s",
        request_id,
        range_id,
    )

    _publish_event(event)


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

    logger.info("Publishing destroyed event: request_id=%s range_id=%s", request_id, range_id)

    _publish_event(event)


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

    logger.info("Publishing cancelled event: request_id=%s range_id=%s", request_id, range_id)

    _publish_event(event)


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
        "Publishing NGFW event: request_id=%s instance_id=%s app_id=%s status=%s serial=%s",
        request_id,
        instance_id,
        app_id,
        status,
        serial_number or "N/A",
    )

    _publish_event(event)
