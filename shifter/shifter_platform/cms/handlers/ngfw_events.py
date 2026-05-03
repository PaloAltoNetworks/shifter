"""NGFW event handler — updates CMS Instance and App for ngfw.event messages."""

from __future__ import annotations

import logging

from cms.handlers.envelope import parse_sns_message
from cms.models import App, Instance
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW

logger = logging.getLogger(__name__)


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

    Also stores serial_number in App.data when provided (on ready events).

    Args:
        event: Event payload with instance_id, app_id, status, serial_number.
    """
    event_id = event.get("event_id", "unknown")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")
    serial_number = event.get("serial_number")

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
        update_fields = []

        if status:
            app.status = status
            update_fields.append("status")

        # Store serial_number in App.data when provided (typically on ready events)
        if serial_number:
            app.data = {**app.data, "serial_number": serial_number}
            update_fields.append("data")

        if update_fields:
            app.save(update_fields=update_fields)
    except App.DoesNotExist:
        logger.warning("CMS App not found: app_id=%s event_id=%s", app_id, event_id)
        previous_app_status = None
    except Exception:
        logger.exception("DB error saving CMS App: app_id=%s event_id=%s", app_id, event_id)
        return

    logger.info(
        "CMS processed NGFW event: instance_id=%s (%s->%s) app_id=%s (%s->%s) serial=%s event_id=%s",
        instance_id,
        previous_instance_status,
        status or previous_instance_status,
        app_id,
        previous_app_status,
        status or previous_app_status,
        serial_number or "N/A",
        event_id,
    )
