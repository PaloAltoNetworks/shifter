"""CMS handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from cms.models import NGFW, RangeInstance
from shared.enums import ResourceStatus, TERMINAL_STATUSES

logger = logging.getLogger(__name__)


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
        logger.debug(
            "Routing to range handler: event_type=%s event_id=%s", event_type, event_id
        )
        process_range_event(message)
    elif event_type.startswith("ngfw."):
        logger.debug(
            "Routing to NGFW handler: event_type=%s event_id=%s", event_type, event_id
        )
        process_ngfw_event(message)
    else:
        logger.debug("Ignoring unknown event_type=%s event_id=%s", event_type, event_id)


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
    event_id = event.get("event_id", "unknown")

    try:
        ResourceStatus(new_status)
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
        "CMS updated RangeInstance: range_id=%s status=%s->%s event_id=%s",
        range_id,
        previous_status,
        new_status,
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process NGFW event from SNS/SQS - updates CMS NGFW.status.

    This handler consumes NGFW status events published by the Engine
    provisioner and updates the CMS NGFW model accordingly.

    Args:
        message: SNS-wrapped message containing NGFW event data.
            Expected event format:
            {
                "event_type": "ngfw.status.updated",
                "ngfw_id": int,  # Engine's NGFW.id
                "cms_ngfw_id": int,  # CMS's NGFW.id for correlation
                "user_id": int,
                "new_status": str,
                "error_message": str | None
            }

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)

    event_type = event.get("event_type")
    if event_type != "ngfw.status.updated":
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    cms_ngfw_id = event.get("cms_ngfw_id")  # CMS's NGFW.id
    user_id = event.get("user_id")
    new_status = event.get("new_status")
    event_id = event.get("event_id", "unknown")

    # CMS only cares about terminal statuses - marks NGFW as deleted
    try:
        status = ResourceStatus(new_status)
    except ValueError:
        logger.error(
            "Invalid NGFW status value: %s (cms_ngfw_id=%s)", new_status, cms_ngfw_id
        )
        return

    if status not in TERMINAL_STATUSES:
        logger.debug(
            "Ignoring non-terminal status: cms_ngfw_id=%s status=%s",
            cms_ngfw_id,
            new_status,
        )
        return

    try:
        ngfw = NGFW.objects.get(id=cms_ngfw_id)
    except NGFW.DoesNotExist:
        logger.warning("CMS NGFW not found: cms_ngfw_id=%s", cms_ngfw_id)
        return

    if ngfw.user_id != user_id:
        logger.error(
            "user_id mismatch: message=%s, ngfw=%s (cms_ngfw_id=%s)",
            user_id,
            ngfw.user_id,
            cms_ngfw_id,
        )
        return

    ngfw.deleted_at = timezone.now()

    try:
        ngfw.save(update_fields=["deleted_at"])
    except Exception:
        logger.exception("DB error saving CMS NGFW: cms_ngfw_id=%s", cms_ngfw_id)
        return

    logger.info(
        "CMS marked NGFW deleted: cms_ngfw_id=%s status=%s event_id=%s",
        cms_ngfw_id,
        new_status,
        event_id,
    )
