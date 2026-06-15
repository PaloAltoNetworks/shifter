"""Range status event handler — updates RangeInstance and fires bridges."""

from __future__ import annotations

import logging

from cms.handlers.ctf_bridge import notify_ctf_range_status
from cms.handlers.experiment_bridge import notify_experiment_on_range_ready
from cms.models import RangeInstance
from shared.enums import ResourceStatus
from shared.messages.envelope import parse_sns_message
from shared.messages.events import EVENT_TYPE_STATUS_UPDATED

logger = logging.getLogger(__name__)


def _lookup_range_instance(request_id, range_id, *, include_deleted=False):
    """Resolve a `RangeInstance` from request_id (new pattern) or range_id (legacy).

    Returns the instance or None; the caller is responsible for short-circuiting
    when this returns None (it has already logged the reason).
    """
    manager = RangeInstance.all_objects if include_deleted else RangeInstance.objects
    if request_id:
        try:
            return manager.get(request__request_id=request_id)
        except RangeInstance.DoesNotExist:
            logger.warning("RangeInstance not found: request_id=%s", request_id)
            return None
    if range_id is not None:
        try:
            return manager.get(range_id=range_id)
        except RangeInstance.DoesNotExist:
            logger.warning("RangeInstance not found: range_id=%s", range_id)
            return None
    logger.warning("Missing both request_id and range_id in event")
    return None


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
    if event_type != EVENT_TYPE_STATUS_UPDATED:
        logger.debug("Ignoring event_type=%s", event_type)
        return

    request_id = event.get("request_id")
    range_id = event.get("range_id")
    user_id = event.get("user_id")
    new_status = event.get("new_status")
    event_id = event.get("event_id", "unknown")

    if new_status is None:
        logger.warning("Missing new_status in event")
        return

    try:
        ResourceStatus(new_status)
    except ValueError:
        logger.error("Invalid status value: %s (range_id=%s)", new_status, range_id)
        return

    include_deleted = new_status == ResourceStatus.DESTROYED.value
    instance = _lookup_range_instance(request_id, range_id, include_deleted=include_deleted)
    if instance is None:
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

    update_fields = ["status"]
    if range_id is not None and instance.range_id is None:
        instance.range_id = range_id
        update_fields.append("range_id")

    try:
        instance.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving RangeInstance: range_id=%s", range_id)
        return

    logger.info(
        "CMS updated RangeInstance: request_id=%s range_id=%s status=%s->%s event_id=%s",
        request_id,
        range_id,
        previous_status,
        new_status,
        event_id,
    )

    # CTF bridge: notify CTF subsystem so it can sync CTFParticipant.range_status.
    notify_ctf_range_status(instance.pk, new_status, previous_status)

    # Experiment bridge: when a range becomes READY and is linked to an
    # experiment run, publish an event to continue execution.
    if new_status == ResourceStatus.READY.value:
        provisioned_instances = event.get("instances", {})
        notify_experiment_on_range_ready(instance, provisioned_instances)
