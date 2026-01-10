"""CMS handlers for processing SNS/SQS range events.

These handlers process range status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from cms.models import RangeInstance
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

    try:
        RangeStatus(new_status)
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
        "CMS updated RangeInstance: range_id=%s status=%s->%s",
        range_id,
        previous_status,
        new_status,
    )
