"""Event publishing for Shifter Engine provisioner.

This module handles publishing range status events to Redis for consumption
by Django Channels workers. It's designed to run without Django, using
direct Redis connections.

Usage from provisioner:
    from events import publish_status_update, publish_ready, publish_failed

    # When status changes
    publish_status_update(range_id=1, user_id=42, old_status="pending", new_status="provisioning")

    # When provisioning completes
    publish_ready(range_id=1, user_id=42, instances=[...])

    # When provisioning fails
    publish_failed(range_id=1, user_id=42, error_message="Subnet exhausted")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import redis
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

# Event type constants (matching shared.messages.events)
EVENT_TYPE_STATUS_UPDATED = "range.status.updated"
EVENT_TYPE_PROVISIONED = "range.provisioned"
EVENT_TYPE_DESTROYED = "range.destroyed"
EVENT_TYPE_CANCELLED = "range.cancelled"

# Status constants (matching shared.enums)
STATUS_PENDING = "pending"
STATUS_PROVISIONING = "provisioning"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DESTROYING = "destroying"
STATUS_DESTROYED = "destroyed"

# Channel names for Django Channels workers
CHANNEL_ENGINE_STATUS = "range.status.engine"
CHANNEL_CMS_STATUS = "range.status.cms"


def _get_redis_client() -> redis.Redis:
    """Get Redis client from environment configuration.

    Returns:
        Redis client connected to configured Redis server.

    Raises:
        ValueError: If REDIS_URL not set in environment.
    """
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise ValueError("REDIS_URL environment variable not set")

    return redis.from_url(redis_url)


def _create_event(
    event_type: str,
    range_id: int,
    user_id: int,
    **kwargs: Any,
) -> dict:
    """Create a standard event envelope.

    Args:
        event_type: Type of event (e.g., "range.status.updated")
        range_id: ID of the range
        user_id: ID of the user who owns the range
        **kwargs: Additional event-specific data

    Returns:
        Event dictionary ready for JSON serialization.
    """
    return {
        "type": "range.status",  # Django Channels message type
        "event_type": event_type,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "range_id": range_id,
        "user_id": user_id,
        **kwargs,
    }


def _publish_to_channels(event: dict) -> None:
    """Publish event to Django Channels via Redis.

    Publishes to both Engine and CMS channel workers using
    the asgi_redis channel layer protocol.

    Args:
        event: Event dictionary to publish.
    """
    client = _get_redis_client()

    # Serialize event to JSON
    message = json.dumps(event)

    range_id = event.get("range_id")

    # Publish to Redis channels for Django Channels workers
    # Using Redis pub/sub for channel layer messages
    for channel in [CHANNEL_ENGINE_STATUS, CHANNEL_CMS_STATUS]:
        try:
            # Use Redis PUBLISH for channel layer
            # The channel layer uses a specific format for routing
            client.publish(f"asgi:{channel}", message)
            logger.debug("Published to channel %s: range_id=%s", channel, range_id)
        except Exception as e:
            logger.error(
                "Failed to publish to channel %s: range_id=%s error=%s",
                channel,
                range_id,
                str(e),
            )

    # Also publish to range-specific channel for WebSocket consumers
    range_channel = f"range_status_{range_id}"
    try:
        client.publish(f"asgi:{range_channel}", message)
        logger.debug("Published to channel %s", range_channel)
    except Exception as e:
        logger.error(
            "Failed to publish to channel %s: error=%s",
            range_channel,
            str(e),
        )


def publish_status_update(
    range_id: int,
    user_id: int,
    old_status: str,
    new_status: str,
    error_message: str | None = None,
) -> None:
    """Publish a status change event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
        old_status: Previous status value
        new_status: New status value
        error_message: Optional error message for failure events
    """
    event = _create_event(
        event_type=EVENT_TYPE_STATUS_UPDATED,
        range_id=range_id,
        user_id=user_id,
        old_status=old_status,
        new_status=new_status,
        error_message=error_message,
    )

    logger.info(
        "Publishing status update: range_id=%s old=%s new=%s",
        range_id,
        old_status,
        new_status,
    )

    _publish_to_channels(event)


def publish_ready(
    range_id: int,
    user_id: int,
    instances: list[dict[str, Any]],
) -> None:
    """Publish a provisioning complete event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
        instances: List of provisioned instance details
    """
    # First publish status update
    publish_status_update(
        range_id=range_id,
        user_id=user_id,
        old_status=STATUS_PROVISIONING,
        new_status=STATUS_READY,
    )

    # Then publish provisioned event with instance details
    event = _create_event(
        event_type=EVENT_TYPE_PROVISIONED,
        range_id=range_id,
        user_id=user_id,
        instances=instances,
    )

    logger.info(
        "Publishing ready event: range_id=%s instances=%d",
        range_id,
        len(instances),
    )

    _publish_to_channels(event)


def publish_failed(
    range_id: int,
    user_id: int,
    error_message: str,
) -> None:
    """Publish a provisioning failure event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
        error_message: Description of the failure
    """
    publish_status_update(
        range_id=range_id,
        user_id=user_id,
        old_status=STATUS_PROVISIONING,
        new_status=STATUS_FAILED,
        error_message=error_message,
    )


def publish_destroyed(range_id: int, user_id: int) -> None:
    """Publish a range destroyed event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
    """
    publish_status_update(
        range_id=range_id,
        user_id=user_id,
        old_status=STATUS_DESTROYING,
        new_status=STATUS_DESTROYED,
    )

    event = _create_event(
        event_type=EVENT_TYPE_DESTROYED,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info("Publishing destroyed event: range_id=%s", range_id)

    _publish_to_channels(event)


def publish_cancelled(range_id: int, user_id: int) -> None:
    """Publish a range cancelled event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
    """
    event = _create_event(
        event_type=EVENT_TYPE_CANCELLED,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info("Publishing cancelled event: range_id=%s", range_id)

    _publish_to_channels(event)
