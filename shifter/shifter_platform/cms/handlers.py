"""CMS handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from cms.models import App, Instance, RangeInstance
from shared.enums import ResourceStatus
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
    """Process range event from SNS/SQS - updates RangeInstance.status.

    This handler consumes range status events published by the Engine
    provisioner and updates the CMS RangeInstance model accordingly.

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
    user_id = event.get("user_id")
    new_status = event.get("new_status")
    event_id = event.get("event_id", "unknown")

    if range_id is None or new_status is None:
        logger.warning("Missing range_id or new_status in event")
        return

    try:
        ResourceStatus(new_status)
    except ValueError:
        logger.error("Invalid status value: %s (range_id=%s)", new_status, range_id)
        return

    try:
        instance = RangeInstance.objects.get(range_id=range_id)
    except RangeInstance.DoesNotExist:
        logger.warning("RangeInstance not found: range_id=%s", range_id)
        return

    if instance.user_id != user_id:
        logger.error(
            "user_id mismatch: message=%s, instance=%s (range_id=%s)",
            user_id,
            instance.user_id,
            range_id,
        )
        return

    previous_status = instance.status
    instance.status = new_status

    try:
        instance.save(update_fields=["status"])
    except Exception:
        logger.exception("DB error saving RangeInstance: range_id=%s", range_id)
        return

    logger.info(
        "CMS updated RangeInstance: range_id=%s status=%s->%s event_id=%s",
        range_id,
        previous_status,
        new_status,
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process unified NGFW event from SNS/SQS.

    Updates CMS Instance and App models based on the event:
    - Looks up Instance by instance_id (UUID)
    - Looks up App by app_id (UUID)
    - Updates status on both if provided
    - EntityBase.save() auto-sets deleted_at on terminal status

    Args:
        message: SNS-wrapped message containing NGFW event data.

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)
    event_type = event.get("event_type")

    if event_type != EVENT_TYPE_NGFW:
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    _handle_ngfw_event(event)


def _handle_ngfw_event(event: dict) -> None:
    """Handle unified ngfw.event - update CMS Instance and App status.

    Args:
        event: Event payload with instance_id, app_id, status.
    """
    event_id = event.get("event_id", "unknown")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")

    # Validate required fields
    if not instance_id or not app_id:
        logger.warning(
            "NGFW event missing required fields: instance_id=%s app_id=%s event_id=%s",
            instance_id,
            app_id,
            event_id,
        )
        return

    # Validate status if provided
    if status:
        try:
            ResourceStatus(status)
        except ValueError:
            logger.error("Invalid status value: %s event_id=%s", status, event_id)
            return

    # Look up and update Instance
    try:
        instance = Instance.objects.get(id=instance_id)
        previous_instance_status = instance.status
        if status:
            instance.status = status
            instance.save(update_fields=["status"])
    except Instance.DoesNotExist:
        logger.warning(
            "CMS Instance not found: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        previous_instance_status = None
    except Exception:
        logger.exception(
            "DB error saving CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return

    # Look up and update App
    try:
        app = App.objects.get(id=app_id)
        previous_app_status = app.status
        if status:
            app.status = status
            app.save(update_fields=["status"])
    except App.DoesNotExist:
        logger.warning("CMS App not found: app_id=%s event_id=%s", app_id, event_id)
        previous_app_status = None
    except Exception:
        logger.exception("DB error saving CMS App: app_id=%s event_id=%s", app_id, event_id)
        return

    logger.info(
        "CMS processed NGFW event: instance_id=%s (%s->%s) app_id=%s (%s->%s) event_id=%s",
        instance_id,
        previous_instance_status,
        status or previous_instance_status,
        app_id,
        previous_app_status,
        status or previous_app_status,
        event_id,
    )
