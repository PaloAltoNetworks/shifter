"""Range status event handler — updates RangeInstance and fires CTF bridge."""

from __future__ import annotations

import logging
from typing import cast

from django.db import transaction

from cms.handlers.ctf_bridge import notify_ctf_range_status
from cms.models import RangeInstance
from shared.enums import ResourceStatus
from shared.messages.envelope import parse_sns_message
from shared.messages.events import EVENT_TYPE_STATUS_UPDATED
from shared.messages.payloads import RangeStatusUpdatedPayload

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


def apply_range_status(
    instance: RangeInstance,
    new_status: str,
    *,
    extra_update_fields: list[str] | None = None,
) -> bool:
    """Update a RangeInstance's status and fire downstream CTF bridge.

    Idempotent: if ``instance.status`` already equals ``new_status`` this
    function is a no-op and returns ``False``.  The caller is responsible for
    validating ``new_status`` and enforcing any forward-only ordering before
    calling this function.

    The status write and the downstream CTF bridge effects are
    committed as a single atomic unit.  If any bridge raises (e.g. a transient
    publish failure), the status update rolls back together with it, so a
    redelivered event is not seen as an already-converged no-op with the bridge
    effect permanently skipped — the worker retry re-runs the whole unit.

    Args:
        instance: The RangeInstance to update.
        new_status: Target status value (must already be validated).
        extra_update_fields: Additional model fields whose values have been
            set on ``instance`` and should be persisted in the same save
            call (e.g. ``["range_id"]`` when the event backfills the id).

    Returns:
        ``True`` if the status was changed and bridges were fired;
        ``False`` when the instance was already at ``new_status`` (no-op).
    """
    if instance.status == new_status:
        return False

    previous_status = instance.status
    instance.status = new_status

    save_fields = ["status"] + (extra_update_fields or [])
    try:
        with transaction.atomic():
            instance.save(update_fields=save_fields)
            notify_ctf_range_status(instance.pk, new_status, previous_status)
    except Exception:
        # Transient DB/broker failure on the save or a bridge effect. The
        # atomic block has rolled the status write back; restore the in-memory
        # value so the object matches the committed DB state, then propagate so
        # the worker retry (or DLQ) re-runs the whole status+bridge unit.
        logger.exception(
            "Failed to apply RangeInstance status pk=%s status=%s — rolled back",
            instance.pk,
            new_status,
        )
        instance.status = previous_status
        raise

    return True


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

    # event_type confirmed; narrow to the typed payload. Runtime shape/ownership
    # validation below is retained — the payload is still untrusted input.
    payload = cast(RangeStatusUpdatedPayload, event)

    request_id = payload.get("request_id")
    range_id = payload.get("range_id")
    user_id = payload.get("user_id")
    new_status = payload.get("new_status")
    event_id = payload.get("event_id", "unknown")

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

    extra_fields: list[str] = []
    if range_id is not None and instance.range_id is None:
        instance.range_id = range_id
        extra_fields.append("range_id")

    applied = apply_range_status(
        instance,
        new_status,
        extra_update_fields=extra_fields or None,
    )

    if applied:
        logger.info(
            "CMS updated RangeInstance: request_id=%s range_id=%s status=%s->%s event_id=%s",
            request_id,
            range_id,
            previous_status,
            new_status,
            event_id,
        )
