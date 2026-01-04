"""Engine handlers for processing SNS/SQS range events.

These handlers process range status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from engine.models import Range
from shared.enums import RangeStatus

logger = logging.getLogger(__name__)


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
    """Process range event from SNS/SQS - updates Range.status and timestamps.

    This handler consumes range status events published by the Engine
    provisioner and updates the Engine Range model accordingly.

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
    error_message = event.get("error_message")

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("Range not found: range_id=%s", range_id)
        return

    if range_obj.user_id != user_id:
        logger.error(
            "user_id mismatch: message=%s, range=%s (range_id=%s)",
            user_id,
            range_obj.user_id,
            range_id,
        )
        return

    previous_status = range_obj.status
    range_obj.status = new_status
    update_fields = ["status"]

    if new_status == RangeStatus.READY.value:
        range_obj.ready_at = timezone.now()
        update_fields.append("ready_at")

    if new_status == RangeStatus.FAILED.value and error_message:
        range_obj.error_message = error_message
        update_fields.append("error_message")

    if new_status == RangeStatus.DESTROYED.value:
        range_obj.destroyed_at = timezone.now()
        update_fields.append("destroyed_at")

    try:
        range_obj.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving Range: range_id=%s", range_id)
        return

    logger.info(
        "Engine updated Range: range_id=%s status=%s->%s",
        range_id,
        previous_status,
        new_status,
    )
