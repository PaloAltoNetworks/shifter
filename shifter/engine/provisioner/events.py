"""Event publishing for Shifter Engine provisioner.

This module handles publishing range status events to SNS for fan-out
to Django Celery workers via SQS queues.

Usage from provisioner:
    from events import publish_status_update, publish_ready, publish_failed

    # When status changes
    publish_status_update(range_id=1, user_id=42, new_status="provisioning")

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

import boto3

logger = logging.getLogger(__name__)

# TODO: #641 shared package
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


def _get_sns_client():
    """Get SNS client with region from environment.

    Returns:
        boto3 SNS client configured for the appropriate region.
    """
    region = os.environ.get("AWS_REGION", "us-east-2")
    return boto3.client("sns", region_name=region)


def _get_sns_topic_arn() -> str:
    """Get SNS topic ARN from environment.

    Returns:
        SNS topic ARN for range events.

    Raises:
        ValueError: If SNS_RANGE_EVENTS_ARN not set in environment.
    """
    arn = os.environ.get("SNS_RANGE_EVENTS_ARN")
    if not arn:
        raise ValueError("SNS_RANGE_EVENTS_ARN environment variable not set")
    return arn


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
        "event_type": event_type,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "range_id": range_id,
        "user_id": user_id,
        **kwargs,
    }


def _publish_event(event: dict) -> None:
    """Publish event to SNS topic.

    Publishes the event to SNS for fan-out to Django Celery workers
    via SQS queues.

    Args:
        event: Event dictionary to publish.
    """
    try:
        sns = _get_sns_client()
        topic_arn = _get_sns_topic_arn()

        sns.publish(
            TopicArn=topic_arn,
            Message=json.dumps(event),
            MessageAttributes={
                "event_type": {
                    "DataType": "String",
                    "StringValue": event.get("event_type", "unknown"),
                }
            },
        )

        logger.debug(
            "Published event to SNS: range_id=%s event_type=%s",
            event.get("range_id"),
            event.get("event_type"),
        )

    except Exception as e:
        logger.error(
            "Failed to publish event to SNS: range_id=%s error=%s",
            event.get("range_id"),
            str(e),
        )


def publish_status_update(
    range_id: int,
    user_id: int,
    new_status: str,
    error_message: str | None = None,
) -> None:
    """Publish a status change event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
        new_status: New status value
        error_message: Optional error message for failure events
    """
    event = _create_event(
        event_type=EVENT_TYPE_STATUS_UPDATED,
        range_id=range_id,
        user_id=user_id,
        new_status=new_status,
        error_message=error_message,
    )

    logger.info(
        "Publishing status update: range_id=%s new_status=%s",
        range_id,
        new_status,
    )

    _publish_event(event)


def publish_ready(
    range_id: int,
    user_id: int,
    instances: list[dict[str, Any]],
    subnet_id: str | None = None,
    subnet_cidr: str | None = None,
    pulumi_stack: str | None = None,
) -> None:
    """Publish a provisioning complete event.

    Args:
        range_id: ID of the range
        user_id: ID of the user who owns the range
        instances: List of provisioned instance details
        subnet_id: AWS subnet ID where instances are provisioned
        subnet_cidr: CIDR block of the provisioned subnet
        pulumi_stack: Name of the Pulumi stack
    """
    # First publish status update
    publish_status_update(
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_READY,
    )

    # Then publish provisioned event with instance details
    event = _create_event(
        event_type=EVENT_TYPE_PROVISIONED,
        range_id=range_id,
        user_id=user_id,
        instances=instances,
        subnet_id=subnet_id,
        subnet_cidr=subnet_cidr,
        pulumi_stack=pulumi_stack,
    )

    logger.info(
        "Publishing ready event: range_id=%s instances=%d",
        range_id,
        len(instances),
    )

    _publish_event(event)


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
        new_status=STATUS_DESTROYED,
    )

    event = _create_event(
        event_type=EVENT_TYPE_DESTROYED,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info("Publishing destroyed event: range_id=%s", range_id)

    _publish_event(event)


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

    _publish_event(event)
