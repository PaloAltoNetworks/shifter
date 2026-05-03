"""CMS event handler package.

Routes SNS/SQS events to per-domain submodules:
- range.*       -> cms.handlers.range_events
- ngfw.*        -> cms.handlers.ngfw_events
- experiment.*  -> cms.experiments.handlers

Public surface preserved for the SQS worker (`cms.handlers.process_event` in
`config/settings.py`) and existing direct importers.
"""

from __future__ import annotations

import logging

from cms.experiments import handlers as experiment_handlers
from cms.handlers.envelope import parse_sns_message
from cms.handlers.experiment_bridge import notify_experiment_on_range_ready
from cms.handlers.ngfw_events import process_ngfw_event
from cms.handlers.range_events import process_range_event

logger = logging.getLogger(__name__)

__all__ = [
    "notify_experiment_on_range_ready",
    "parse_sns_message",
    "process_event",
    "process_ngfw_event",
    "process_range_event",
]


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

    # Dispatch via the package-level globals so that monkeypatches /
    # instrumentation attached to the documented public names
    # (`cms.handlers.process_range_event`, `cms.handlers.process_ngfw_event`)
    # still intercept worker dispatch — same behavior as the pre-split module.
    if event_type.startswith("range."):
        logger.debug("Routing to range handler: event_type=%s event_id=%s", event_type, event_id)
        process_range_event(message)
    elif event_type.startswith("ngfw."):
        logger.debug("Routing to NGFW handler: event_type=%s event_id=%s", event_type, event_id)
        process_ngfw_event(message)
    elif event_type.startswith("experiment."):
        logger.debug("Routing to experiment handler: event_type=%s event_id=%s", event_type, event_id)
        experiment_handlers.process_event(message)
    else:
        logger.debug("Ignoring unknown event_type=%s event_id=%s", event_type, event_id)
