"""Mission Control handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates and broadcast them to WebSocket clients.
"""

from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.channels.groups import ngfw_event_group, range_event_group
from shared.messages.events import EVENT_TYPE_NGFW

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
                "request_id": str (UUID) - required
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

    request_id = event.get("request_id")
    new_status = event.get("new_status")
    error_message = event.get("error_message")
    event_id = event.get("event_id", "unknown")

    if not request_id:
        logger.error("Missing request_id in range event: event_id=%s", event_id)
        return

    channel_layer = get_channel_layer()
    group_name = range_event_group(str(request_id))

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "range.status",
            "request_id": str(request_id),
            "new_status": new_status,
            "error_message": error_message,
        },
    )

    logger.info(
        "MC broadcast to group %s: request_id=%s status=%s event_id=%s",
        group_name,
        request_id,
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
                "event_type": "ngfw.event",
                "request_id": str (UUID),
                "instance_id": str (UUID),
                "app_id": str (UUID),
                "status": str | None,
                "state": dict | None
            }

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != EVENT_TYPE_NGFW:
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    app_id = event.get("app_id")
    status = event.get("status")
    state = event.get("state") or {}
    serial_number = event.get("serial_number")
    event_id = event.get("event_id", "unknown")

    if not app_id or not isinstance(app_id, str):
        logger.warning("Invalid app_id: %s", app_id)
        return

    channel_layer = get_channel_layer()
    group_name = ngfw_event_group(app_id)

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ngfw.status",
            "app_id": app_id,
            "status": status,
            "state": state,
            "serial_number": serial_number,
        },
    )

    logger.info(
        "MC broadcast to group %s: app_id=%s status=%s event_id=%s",
        group_name,
        app_id,
        status,
        event_id,
    )
