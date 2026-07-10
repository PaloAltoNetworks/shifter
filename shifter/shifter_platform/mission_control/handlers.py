"""Mission Control handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates and broadcast them to WebSocket clients.
"""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.channels.groups import ngfw_event_group, range_event_group
from shared.channels.payloads import NGFWStatusChannelEvent, RangeStatusChannelEvent
from shared.enums import ResourceStatus
from shared.messages.envelope import parse_sns_message
from shared.messages.events import EVENT_TYPE_NGFW
from shared.messages.payloads import NGFWEventPayload, RangeStatusUpdatedPayload
from shared.schemas import RangeRef

logger = logging.getLogger(__name__)


def _range_ref_from_status_event(event: RangeStatusUpdatedPayload) -> RangeRef | None:
    """Build RangeRef from a range.status.updated event payload, or None when invalid."""
    event_id = event.get("event_id", "unknown")
    request_id = event.get("request_id")
    new_status = event.get("new_status")
    user_id = event.get("user_id")

    # request_id is typed str, but the event is untrusted input: a non-string
    # (numeric JSON, or a UUID object from a direct caller) must be dropped, not
    # crash UUID() with an uncaught AttributeError. isinstance also narrows for
    # the UUID() coercion below.
    if not isinstance(request_id, str) or not request_id or new_status is None or user_id is None:
        logger.error(
            "Invalid range status event payload: event_id=%s request_id=%s new_status=%s user_id=%s",
            event_id,
            request_id,
            new_status,
            user_id,
        )
        return None

    try:
        return RangeRef(
            request_id=UUID(request_id),
            range_id=event.get("range_id"),
            user_id=user_id,
            status=ResourceStatus(new_status),
        )
    except (ValueError, TypeError):
        logger.error(
            "Invalid range status event payload: event_id=%s request_id=%s",
            event_id,
            request_id,
        )
        return None


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


def process_range_event(message: str | dict) -> None:
    """Process range event from SNS/SQS - push to WebSocket via Channels.

    This handler consumes range status events published by the Engine
    provisioner and broadcasts them to connected WebSocket clients
    via the Django Channels layer.  MC fanout is advisory (UI only) — if the
    channel layer is not configured the event is acknowledged without broadcast
    so the worker is never blocked or forced to retry on a UI-only transport.

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
        None.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != "range.status.updated":
        logger.debug("Ignoring event_type=%s", event_type)
        return

    payload = cast(RangeStatusUpdatedPayload, event)
    range_ref = _range_ref_from_status_event(payload)
    if range_ref is None:
        return

    error_message = payload.get("error_message")
    event_id = payload.get("event_id", "unknown")

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning(
            "MC range event: channel layer not configured — acking without broadcast (request_id=%s event_id=%s)",
            range_ref.request_id,
            event_id,
        )
        return
    group_name = range_event_group(str(range_ref.request_id))

    channel_event: RangeStatusChannelEvent = {
        "type": "range.status",
        "range_ref": range_ref.model_dump(mode="json"),
        "request_id": str(range_ref.request_id),
        "new_status": range_ref.status.value,
        "error_message": error_message,
    }
    async_to_sync(channel_layer.group_send)(group_name, channel_event)

    logger.info(
        "MC broadcast to group %s: request_id=%s status=%s event_id=%s",
        group_name,
        range_ref.request_id,
        range_ref.status.value,
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process NGFW event from SNS/SQS - push to WebSocket via Channels.

    This handler consumes NGFW status events published by the Engine
    provisioner and broadcasts them to connected WebSocket clients
    via the Django Channels layer.  MC fanout is advisory (UI only) — if the
    channel layer is not configured the event is acknowledged without broadcast
    so the worker is never blocked or forced to retry on a UI-only transport.

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
        None.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != EVENT_TYPE_NGFW:
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    payload = cast(NGFWEventPayload, event)
    app_id = payload.get("app_id")
    status = payload.get("status")
    state = payload.get("state") or {}
    serial_number = payload.get("serial_number")
    event_id = payload.get("event_id", "unknown")

    if not app_id or not isinstance(app_id, str):
        logger.warning("Invalid app_id: %s", app_id)
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning(
            "MC ngfw event: channel layer not configured — acking without broadcast (app_id=%s event_id=%s)",
            app_id,
            event_id,
        )
        return
    group_name = ngfw_event_group(app_id)

    channel_event: NGFWStatusChannelEvent = {
        "type": "ngfw.status",
        "app_id": app_id,
        "status": status,
        "state": state,
        "serial_number": serial_number,
    }
    async_to_sync(channel_layer.group_send)(group_name, channel_event)

    logger.info(
        "MC broadcast to group %s: app_id=%s status=%s event_id=%s",
        group_name,
        app_id,
        status,
        event_id,
    )
