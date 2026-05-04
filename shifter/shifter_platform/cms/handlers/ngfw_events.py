"""NGFW event handler — updates CMS Instance and App for ngfw.event messages."""

from __future__ import annotations

import logging

from cms.models import App, Instance
from shared.enums import ResourceStatus
from shared.messages.envelope import parse_sns_message
from shared.messages.events import EVENT_TYPE_NGFW

logger = logging.getLogger(__name__)


class _NgfwAbort(Exception):
    """Internal: raised by an entity update helper when a DB error has been
    logged and the rest of the event handler should bail out cleanly."""


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

    event_id = event.get("event_id", "unknown")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")
    serial_number = event.get("serial_number")

    if not _validate_required_fields(event_id, instance_id, app_id):
        return
    if not _validate_status(event_id, status):
        return
    # _validate_required_fields confirms both are truthy; narrow for type checkers.
    assert instance_id is not None
    assert app_id is not None

    try:
        previous_instance_status = _update_instance(event_id, instance_id, status)
        previous_app_status = _update_app(event_id, app_id, status, serial_number)
    except _NgfwAbort:
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


def _validate_required_fields(event_id: str, instance_id: str | None, app_id: str | None) -> bool:
    if instance_id and app_id:
        return True
    logger.warning(
        "NGFW event missing required fields: instance_id=%s app_id=%s event_id=%s",
        instance_id,
        app_id,
        event_id,
    )
    return False


def _validate_status(event_id: str, status: str | None) -> bool:
    if not status:
        return True
    try:
        ResourceStatus(status)
    except ValueError:
        logger.error("Invalid status value: %s event_id=%s", status, event_id)
        return False
    return True


def _update_instance(event_id: str, instance_id: str, status: str | None) -> str | None:
    """Look up Instance and apply status. Returns previous status, or None if
    the row is missing. Raises `_NgfwAbort` on DB error."""
    try:
        instance = Instance.objects.get(id=instance_id)
    except Instance.DoesNotExist:
        logger.warning(
            "CMS Instance not found: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return None
    except Exception as exc:
        logger.exception(
            "DB error loading CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        raise _NgfwAbort from exc

    previous = instance.status
    if not status:
        return previous

    instance.status = status
    try:
        instance.save(update_fields=["status"])
    except Exception as exc:
        logger.exception(
            "DB error saving CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        raise _NgfwAbort from exc
    return previous


def _update_app(
    event_id: str,
    app_id: str,
    status: str | None,
    serial_number: str | None,
) -> str | None:
    """Look up App and apply status / serial_number. Returns previous status,
    or None if the row is missing. Raises `_NgfwAbort` on DB error."""
    try:
        app = App.objects.get(id=app_id)
    except App.DoesNotExist:
        logger.warning("CMS App not found: app_id=%s event_id=%s", app_id, event_id)
        return None
    except Exception as exc:
        logger.exception("DB error loading CMS App: app_id=%s event_id=%s", app_id, event_id)
        raise _NgfwAbort from exc

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
    except Exception as exc:
        logger.exception("DB error saving CMS App: app_id=%s event_id=%s", app_id, event_id)
        raise _NgfwAbort from exc
    return previous
