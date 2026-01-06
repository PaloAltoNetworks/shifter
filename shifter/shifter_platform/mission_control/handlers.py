"""Mission Control handlers for processing SNS/SQS range events.

These handlers process range status updates and broadcast them to WebSocket clients.
"""

from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.channels.groups import range_event_group

logger = logging.getLogger(__name__)


def parse_sns_message(message: str | dict) -> dict:
    """Unwrap SNS envelope to get event payload.

    SNS wraps messages in an envelope with a "Message" key containing
    the actual event payload as a JSON string.

    Args:
        message: Either a dict (SNS envelope or direct event) or
                 a JSON string representation of either.

    Returns:
        The parsed event payload as a dict.
    """
    body = json.loads(message) if isinstance(message, str) else message

    if "Message" in body:
        return json.loads(body["Message"])

    return body


def process_range_event(message: str | dict) -> None:
    """Process range event from SNS/SQS - push to WebSocket via Channels.

    This handler consumes range status events published by the Engine
    provisioner and broadcasts them to connected WebSocket clients
    via the Django Channels layer.

    Args:
        message: SNS-wrapped message containing range event data.
            Expected event format:
            {
                "event_type": "range.status.updated",
                "range_id": int,
                "user_id": int,
                "new_status": str,
                "error_message": str | None
            }

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != "range.status.updated":
        logger.debug("Ignoring event_type=%s", event_type)
        return

    range_id = event.get("range_id")
    new_status = event.get("new_status")
    error_message = event.get("error_message")

    channel_layer = get_channel_layer()
    group_name = range_event_group(range_id)

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "range.status",
            "range_id": range_id,
            "new_status": new_status,
            "error_message": error_message,
        },
    )

    logger.info(
        "MC broadcast to group %s: range_id=%s status=%s",
        group_name,
        range_id,
        new_status,
    )
