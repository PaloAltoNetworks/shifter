"""Range status/provisioned event state application.

Applies authoritative range state changes from provisioner events and writes
the accompanying audit records. Split out of ``engine/handlers.py`` (#685).
Transient DB/audit failures propagate so the worker retries (ADR-025); missing,
unauthorized, or malformed messages log and return.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from engine.models import Range
from shared.audit import AuditEntityType, StateChange, audit_log_system_event
from shared.enums import ResourceStatus
from shared.messages.payloads import RangeProvisionedPayload, RangeStatusUpdatedPayload

from ._audit import _status_to_action

# Stable "engine.handlers" logger namespace (conftest propagation list, audit
# source parity) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.handlers")


def _resolve_authorized_range(event: RangeStatusUpdatedPayload) -> Range | None:
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


def _handle_status_updated(event: RangeStatusUpdatedPayload) -> None:
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

    now = timezone.now()
    previous_status = range_obj.status
    range_obj.status = new_status
    # auto_now on updated_at is bypassed when save(update_fields=...) omits the
    # field, so set it explicitly and include it in the partial save.
    range_obj.updated_at = now
    update_fields = ["status", "updated_at"]

    if new_status == ResourceStatus.READY.value:
        range_obj.ready_at = now
        update_fields.append("ready_at")

    if new_status == ResourceStatus.FAILED.value and error_message:
        range_obj.error_message = error_message
        update_fields.append("error_message")

    if new_status == ResourceStatus.FAILED.value:
        from engine.launch_intents import clear_provisioner_operation_after_failure

        update_fields.extend(clear_provisioner_operation_after_failure(range_obj))

    if new_status == ResourceStatus.DESTROYED.value:
        range_obj.destroyed_at = now
        update_fields.append("destroyed_at")

    try:
        range_obj.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving Range: range_id=%s", range_id)
        # transient DB failure — propagate so the worker/DLQ can retry
        raise

    # Audit log the status change
    audit_log_system_event(
        entity_type=AuditEntityType.RANGE,
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


def _handle_provisioned(event: RangeProvisionedPayload) -> None:
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
