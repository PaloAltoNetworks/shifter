"""Engine event handlers (package facade).

Processes range and NGFW status updates from the Shifter Engine provisioner
delivered over SNS/SQS. Envelope parsing and event-type routing live here; the
range state application, NGFW notification handling, and audit-action mapping
live in private submodules (``_range``, ``_ngfw``, ``_audit``) and are wired in
here (#685). ``engine.handlers.process_event`` remains the SQS worker entry
point (referenced by dotted path in ``config``); ``parse_sns_message`` is
re-exported for callers that import it from this package.
"""

from __future__ import annotations

import logging
from typing import cast

from engine.services import record_aces_operation_status, record_aces_runtime_snapshot
from shared.aces.contracts import EVENT_TYPE_ACES_OPERATION, EVENT_TYPE_ACES_SNAPSHOT
from shared.messages.envelope import parse_sns_message
from shared.messages.events import (
    EVENT_TYPE_NGFW,
    EVENT_TYPE_PROVISIONED,
    EVENT_TYPE_STATUS_UPDATED,
)
from shared.messages.payloads import (
    NGFWEventPayload,
    RangeProvisionedPayload,
    RangeStatusUpdatedPayload,
)

from ._ngfw import _handle_ngfw_event
from ._range import _handle_provisioned, _handle_status_updated

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
        _handle_status_updated(cast(RangeStatusUpdatedPayload, event))
    elif event_type == EVENT_TYPE_PROVISIONED:
        _handle_provisioned(cast(RangeProvisionedPayload, event))
    elif event_type == EVENT_TYPE_ACES_OPERATION:
        record_aces_operation_status(cast("dict", event))
    elif event_type == EVENT_TYPE_ACES_SNAPSHOT:
        record_aces_runtime_snapshot(cast("dict", event))
    else:
        logger.debug("Ignoring event_type=%s", event_type)


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

    _handle_ngfw_event(cast(NGFWEventPayload, event))
