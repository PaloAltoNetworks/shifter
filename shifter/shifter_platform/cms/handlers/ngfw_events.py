"""NGFW event handler — updates CMS Instance and App for ngfw.event messages."""

from __future__ import annotations

import logging

from cms.handlers.envelope import parse_sns_message
from cms.models import App, Instance
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW

logger = logging.getLogger(__name__)

# Sentinel returned by per-entity helpers to distinguish "skip the rest of the
# event" (DB error or invalid input we already logged) from "row missing, but
# carry on" (None) and "row found, here's the prior status" (str).
_ABORT = object()


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

    if not _validate_required_fields(event_id, instance_id, app_id):
        return
    if not _validate_status(event_id, status):
        return

    previous_instance_status = _update_instance(event_id, instance_id, status)
    if previous_instance_status is _ABORT:
        return

    previous_app_status = _update_app(event_id, app_id, status, serial_number)
    if previous_app_status is _ABORT:
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


def _validate_required_fields(event_id: str, instance_id, app_id) -> bool:
    if instance_id and app_id:
        return True
    logger.warning(
        "NGFW event missing required fields: instance_id=%s app_id=%s event_id=%s",
        instance_id,
        app_id,
        event_id,
    )
    return False


def _validate_status(event_id: str, status) -> bool:
    if not status:
        return True
    try:
        ResourceStatus(status)
    except ValueError:
        logger.error("Invalid status value: %s event_id=%s", status, event_id)
        return False
    return True


def _update_instance(event_id: str, instance_id, status):
    """Look up Instance and apply status. Returns previous status, None if
    missing, or the _ABORT sentinel on DB error."""
    try:
        instance = Instance.objects.get(id=instance_id)
    except Instance.DoesNotExist:
        logger.warning(
            "CMS Instance not found: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return None
    except Exception:
        logger.exception(
            "DB error loading CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return _ABORT

    previous = instance.status
    if not status:
        return previous

    instance.status = status
    try:
        instance.save(update_fields=["status"])
    except Exception:
        logger.exception(
            "DB error saving CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return _ABORT
    return previous


def _update_app(event_id: str, app_id, status, serial_number):
    """Look up App and apply status / serial_number. Returns previous status,
    None if missing, or the _ABORT sentinel on DB error."""
    try:
        app = App.objects.get(id=app_id)
    except App.DoesNotExist:
        logger.warning("CMS App not found: app_id=%s event_id=%s", app_id, event_id)
        return None
    except Exception:
        logger.exception("DB error loading CMS App: app_id=%s event_id=%s", app_id, event_id)
        return _ABORT

    previous = app.status
    update_fields: list[str] = []

    if status:
        app.status = status
        update_fields.append("status")

    if serial_number:
        app.data = {**app.data, "serial_number": serial_number}
        update_fields.append("data")

    if not update_fields:
        return previous

    try:
        app.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving CMS App: app_id=%s event_id=%s", app_id, event_id)
        return _ABORT
    return previous
