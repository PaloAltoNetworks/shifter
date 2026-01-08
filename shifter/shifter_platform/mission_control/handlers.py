"""Mission Control handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates and broadcast them to WebSocket clients.
"""

from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.channels.groups import ngfw_event_group, range_event_group

logger = logging.getLogger(__name__)


def process_event(message: str | dict) -> None:
    """Route event to appropriate handler based on event_type.

    This is the main entry point for the SQS worker. It dispatches
    to range or NGFW handlers based on the event_type prefix.

    Args:
        message: SNS-wrapped message containing event data.
    """
    event = parse_sns_message(message)
    event_type = event.get("event_type", "")
    event_id = event.get("event_id", "unknown")

    if event_type.startswith("range."):
        logger.debug("Routing to range handler: event_type=%s event_id=%s", event_type, event_id)
        process_range_event(message)
    elif event_type.startswith("ngfw."):
        logger.debug("Routing to NGFW handler: event_type=%s event_id=%s", event_type, event_id)
        process_ngfw_event(message)
    else:
        logger.debug("Ignoring unknown event_type=%s event_id=%s", event_type, event_id)


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
    event_id = event.get("event_id", "unknown")

    if not isinstance(range_id, int):
        logger.warning("Invalid range_id type: %s", type(range_id))
        return

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
        "MC broadcast to group %s: range_id=%s status=%s event_id=%s",
        group_name,
        range_id,
        new_status,
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process NGFW event from SNS/SQS - push to WebSocket via Channels.

    This handler consumes NGFW status events published by the Engine
    provisioner and broadcasts them to connected WebSocket clients
    via the Django Channels layer.

    Args:
        message: SNS-wrapped message containing NGFW event data.
            Expected event format:
            {
                "event_type": "ngfw.status.updated",
                "ngfw_id": int,  # Engine's NGFW.id
                "cms_ngfw_id": int,  # CMS's NGFW.id for correlation
                "user_id": int,
                "new_status": str,
                "error_message": str | None
            }

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != "ngfw.status.updated":
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    cms_ngfw_id = event.get("cms_ngfw_id")
    new_status = event.get("new_status")
    error_message = event.get("error_message")
    event_id = event.get("event_id", "unknown")

    if not isinstance(cms_ngfw_id, int):
        logger.warning("Invalid cms_ngfw_id type: %s", type(cms_ngfw_id))
        return

    channel_layer = get_channel_layer()
    group_name = ngfw_event_group(cms_ngfw_id)

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ngfw.status",
            "ngfw_id": cms_ngfw_id,
            "new_status": new_status,
            "error_message": error_message,
        },
    )

    logger.info(
        "MC broadcast to group %s: ngfw_id=%s status=%s event_id=%s",
        group_name,
        cms_ngfw_id,
        new_status,
        event_id,
    )
