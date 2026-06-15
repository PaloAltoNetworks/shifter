"""Engine handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from engine.models import Range
from risk_register.models import AuditLog
from risk_register.services import StateChange, audit_log_system_event
from shared.enums import ResourceStatus
from shared.messages.envelope import parse_sns_message
from shared.messages.events import (
    EVENT_TYPE_NGFW,
    EVENT_TYPE_PROVISIONED,
    EVENT_TYPE_STATUS_UPDATED,
)

logger = logging.getLogger(__name__)


def _status_to_action(status: str) -> str:
    """Map range status to audit action."""
    status_action_map = {
        ResourceStatus.READY.value: AuditLog.Action.READY,
        ResourceStatus.FAILED.value: AuditLog.Action.FAILED,
        ResourceStatus.DESTROYED.value: AuditLog.Action.DEPROVISION,
        ResourceStatus.PROVISIONING.value: AuditLog.Action.PROVISION,
        ResourceStatus.DESTROYING.value: AuditLog.Action.DEPROVISION,
    }
    return status_action_map.get(status, AuditLog.Action.UPDATE)


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
    """Process range event from SNS/SQS - updates Range model.

    This handler consumes range events published by the Engine provisioner:
    - range.status.updated: Updates status and timestamps
    - range.provisioned: Updates provisioned_instances with instance details

    Args:
        message: SNS-wrapped message containing range event data.

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")

    if event_type == EVENT_TYPE_STATUS_UPDATED:
        _handle_status_updated(event)
    elif event_type == EVENT_TYPE_PROVISIONED:
        _handle_provisioned(event)
    else:
        logger.debug("Ignoring event_type=%s", event_type)


def _resolve_authorized_range(event: dict[str, Any]) -> Range | None:
    """Resolve and authorize the range targeted by a status-update event.

    Returns None (after logging) when the event is missing identifiers, the
    range does not exist, or the event's user does not own it.
    """
    range_id = event.get("range_id")
    if range_id is None or event.get("new_status") is None:
        logger.warning("Missing range_id or new_status in event")
        return None

    range_obj: Range | None
    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("Range not found: range_id=%s", range_id)
        return None

    if range_obj.user_id != event.get("user_id"):
        logger.error(
            "user_id mismatch: message=%s, range=%s (range_id=%s)",
            event.get("user_id"),
            range_obj.user_id,
            range_id,
        )
        range_obj = None
    return range_obj


def _handle_status_updated(event: dict[str, Any]) -> None:
    """Handle range.status.updated event - update status and timestamps.

    Args:
        event: Event payload with range_id, user_id, new_status, error_message.
    """
    range_obj = _resolve_authorized_range(event)
    if range_obj is None:
        return

    # _resolve_authorized_range guarantees both keys are present and non-None.
    range_id = event["range_id"]
    new_status = event["new_status"]
    error_message = event.get("error_message")
    event_id = event.get("event_id", "unknown")

    previous_status = range_obj.status
    range_obj.status = new_status
    update_fields = ["status"]

    if new_status == ResourceStatus.READY.value:
        range_obj.ready_at = timezone.now()
        update_fields.append("ready_at")

    if new_status == ResourceStatus.FAILED.value and error_message:
        range_obj.error_message = error_message
        update_fields.append("error_message")

    if new_status == ResourceStatus.DESTROYED.value:
        range_obj.destroyed_at = timezone.now()
        update_fields.append("destroyed_at")

    try:
        range_obj.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving Range: range_id=%s", range_id)
        return

    # Audit log the status change
    audit_log_system_event(
        entity_type=AuditLog.EntityType.RANGE,
        entity_id=range_id,
        action=_status_to_action(new_status),
        source="engine.handlers",
        state=StateChange(
            previous={"status": previous_status},
            new={"status": new_status},
        ),
        context=error_message or "",
        request_id=event_id,
    )

    logger.info(
        "Engine updated Range: range_id=%s status=%s->%s event_id=%s",
        range_id,
        previous_status,
        new_status,
        event_id,
    )


def _handle_provisioned(event: dict[str, Any]) -> None:
    """Handle range.provisioned event notification - log only, no DB updates.

    The provisioner writes all state directly to the database (instances,
    subnets). This handler serves as an audit trail for provisioning events.

    Args:
        event: Event payload with range_id, user_id, request_id.
    """
    event_id = event.get("event_id", "unknown")
    request_id = event.get("request_id")
    range_id = event.get("range_id")
    user_id = event.get("user_id")

    # Log the event for audit purposes
    logger.info(
        "Engine received range.provisioned: request_id=%s range_id=%s user_id=%s event_id=%s",
        request_id,
        range_id,
        user_id,
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process NGFW lifecycle notification from SNS/SQS.

    This is a notification-only handler. All state updates are performed
    directly by the provisioner - this handler just logs receipt for
    audit/debugging purposes.

    Args:
        message: SNS-wrapped message containing NGFW event notification.

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)
    event_type = event.get("event_type")

    if event_type != EVENT_TYPE_NGFW:
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    _handle_ngfw_event(event)


def _handle_ngfw_event(event: dict[str, Any]) -> None:
    """Handle NGFW event notification - log only, no DB updates.

    The provisioner writes all state directly to the database.
    This handler serves as:
    - Audit trail for NGFW lifecycle events
    - Notification consumer for other services (MC, CMS)

    Args:
        event: Event payload with request_id, instance_id, app_id, status.
    """
    event_id = event.get("event_id", "unknown")
    request_id = event.get("request_id")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")

    # Audit log the NGFW status change
    audit_log_system_event(
        entity_type=AuditLog.EntityType.NGFW,
        entity_id=app_id or 0,
        action=_status_to_action(status) if status else AuditLog.Action.UPDATE,
        source="engine.handlers",
        state=StateChange(
            new={
                "status": status,
                "instance_id": instance_id,
            }
        ),
        request_id=str(request_id) if request_id else event_id,
    )

    # Log the event for audit purposes
    logger.info(
        "Engine received NGFW event: request_id=%s instance_id=%s app_id=%s status=%s event_id=%s",
        request_id,
        instance_id,
        app_id,
        status,
        event_id,
    )
