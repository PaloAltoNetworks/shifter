"""Engine signal receivers for engine events.

These receivers replace the SQS worker handler (engine.handlers.process_event).
They connect to Django signals emitted by the engine provisioner and update
Engine models (Range).
"""

from __future__ import annotations

import logging

from django.dispatch import receiver
from django.utils import timezone

from engine.models import Range
from engine.signals import range_provisioned, range_status_changed
from shared.enums import ResourceStatus

logger = logging.getLogger(__name__)


@receiver(range_status_changed)
def on_range_status_changed(sender, **kwargs) -> None:
    """Update Range model on status change.

    Replaces engine.handlers._handle_status_updated.
    """
    range_id = kwargs.get("range_id")
    user_id = kwargs.get("user_id")
    new_status = kwargs.get("new_status")
    error_message = kwargs.get("error_message")

    if range_id is None or new_status is None:
        logger.warning("on_range_status_changed: missing range_id or new_status")
        return

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("on_range_status_changed: Range not found range_id=%s", range_id)
        return

    if range_obj.user_id != user_id:
        logger.error(
            "on_range_status_changed: user_id mismatch signal=%s range=%s (range_id=%s)",
            user_id,
            range_obj.user_id,
            range_id,
        )
        return

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
        logger.exception("on_range_status_changed: DB error saving Range range_id=%s", range_id)
        return

    logger.info(
        "Engine updated Range: range_id=%s status=%s->%s",
        range_id,
        previous_status,
        new_status,
    )


@receiver(range_provisioned)
def on_range_provisioned(sender, **kwargs) -> None:
    """Log range provisioned event (audit trail).

    Replaces engine.handlers._handle_provisioned.
    """
    request_id = kwargs.get("request_id")
    range_id = kwargs.get("range_id")
    user_id = kwargs.get("user_id")

    logger.info(
        "Engine received range_provisioned: request_id=%s range_id=%s user_id=%s",
        request_id,
        range_id,
        user_id,
    )
