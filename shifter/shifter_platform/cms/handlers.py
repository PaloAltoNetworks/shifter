"""CMS handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates from the Shifter Engine provisioner.
Includes a bridge that detects experiment-linked ranges and publishes experiment events.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cms.experiments import handlers as experiment_handlers
from cms.experiments.events import publish_range_provisioned_for_experiment
from cms.models import App, Instance, RangeInstance
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW

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
    elif event_type.startswith("experiment."):
        logger.debug("Routing to experiment handler: event_type=%s event_id=%s", event_type, event_id)
        experiment_handlers.process_event(message)
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

    # Look up RangeInstance - prefer request_id (new pattern), fall back to range_id (legacy)
    instance = None
    try:
        if request_id:
            instance = RangeInstance.objects.get(request__request_id=request_id)
        elif range_id is not None:
            instance = RangeInstance.objects.get(range_id=range_id)
        else:
            logger.warning("Missing both request_id and range_id in event")
            return
    except RangeInstance.DoesNotExist:
        logger.warning(
            "RangeInstance not found: request_id=%s range_id=%s",
            request_id,
            range_id,
        )
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
        "CMS updated RangeInstance: request_id=%s range_id=%s status=%s->%s event_id=%s",
        request_id,
        range_id,
        previous_status,
        new_status,
        event_id,
    )

    # --- Experiment bridge ---
    # When a range becomes READY and is linked to an experiment run,
    # publish an event to the experiments SQS queue to continue execution.
    if new_status == ResourceStatus.READY.value:
        provisioned_instances = event.get("instances", {})
        notify_experiment_on_range_ready(instance, provisioned_instances)


# =============================================================================
# Experiment Bridge
# =============================================================================


def notify_experiment_on_range_ready(
    range_instance: RangeInstance,
    provisioned_instances: dict[str, Any],
) -> None:
    """Bridge range provisioned events to the experiment lifecycle.

    Checks if the given RangeInstance is linked to an ExperimentRun
    (via request_id correlation). If so, publishes an
    experiment.run.range_provisioned event to the experiments SQS queue.

    Args:
        range_instance: The RangeInstance that just became READY.
        provisioned_instances: Dict of instance name -> instance details
            from the provisioning event payload.
    """
    from cms.experiments.models import ExperimentRun

    request_id = range_instance.request.request_id if range_instance.request else None
    if request_id is None:
        return

    try:
        run = ExperimentRun.objects.select_related("experiment").get(
            request_id=request_id,
        )
    except ExperimentRun.DoesNotExist:
        # Range is not linked to an experiment — normal interactive range
        return

    logger.info(
        "notify_experiment_on_range_ready: range for experiment=%d run=%d is READY, publishing event (request_id=%s)",
        run.experiment_id,
        run.pk,
        request_id,
    )

    try:
        publish_range_provisioned_for_experiment(
            experiment_id=run.experiment_id,
            run_id=run.pk,
            provisioned_instances=provisioned_instances,
        )
    except Exception:
        # Experiments require deterministic outcomes. If we cannot notify the
        # experiment that its range is ready, the run cannot proceed and must
        # be marked as FAILED to avoid silent orphaning.
        logger.exception(
            "notify_experiment_on_range_ready: failed to publish event for "
            "experiment=%d run=%d (request_id=%s) — marking run as FAILED",
            run.experiment_id,
            run.pk,
            request_id,
        )
        from cms.experiments.schemas import RunStatus

        run.error_message = "Failed to publish range provisioning notification"
        run.save(update_fields=["error_message"])
        run.transition_to(RunStatus.FAILED)


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process unified NGFW event from SNS/SQS.

    Updates CMS Instance and App models based on the event:
    - Looks up Instance by instance_id (UUID)
    - Looks up App by app_id (UUID)
    - Updates status on both if provided
    - EntityBase.save() auto-sets deleted_at on terminal status

    Args:
        message: SNS-wrapped message containing NGFW event data.

    Returns:
        None. Errors are logged and handled gracefully.
    """
    event = parse_sns_message(message)
    event_type = event.get("event_type")

    if event_type != EVENT_TYPE_NGFW:
        logger.debug("Ignoring NGFW event_type=%s", event_type)
        return

    _handle_ngfw_event(event)


def _handle_ngfw_event(event: dict) -> None:
    """Handle unified ngfw.event - update CMS Instance and App status.

    Also stores serial_number in App.data when provided (on ready events).

    Args:
        event: Event payload with instance_id, app_id, status, serial_number.
    """
    event_id = event.get("event_id", "unknown")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")
    serial_number = event.get("serial_number")

    # Validate required fields
    if not instance_id or not app_id:
        logger.warning(
            "NGFW event missing required fields: instance_id=%s app_id=%s event_id=%s",
            instance_id,
            app_id,
            event_id,
        )
        return

    # Validate status if provided
    if status:
        try:
            ResourceStatus(status)
        except ValueError:
            logger.error("Invalid status value: %s event_id=%s", status, event_id)
            return

    # Look up and update Instance
    try:
        instance = Instance.objects.get(id=instance_id)
        previous_instance_status = instance.status
        if status:
            instance.status = status
            instance.save(update_fields=["status"])
    except Instance.DoesNotExist:
        logger.warning(
            "CMS Instance not found: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        previous_instance_status = None
    except Exception:
        logger.exception(
            "DB error saving CMS Instance: instance_id=%s event_id=%s",
            instance_id,
            event_id,
        )
        return

    # Look up and update App
    try:
        app = App.objects.get(id=app_id)
        previous_app_status = app.status
        update_fields = []

        if status:
            app.status = status
            update_fields.append("status")

        # Store serial_number in App.data when provided (typically on ready events)
        if serial_number:
            app.data = {**app.data, "serial_number": serial_number}
            update_fields.append("data")

        if update_fields:
            app.save(update_fields=update_fields)
    except App.DoesNotExist:
        logger.warning("CMS App not found: app_id=%s event_id=%s", app_id, event_id)
        previous_app_status = None
    except Exception:
        logger.exception("DB error saving CMS App: app_id=%s event_id=%s", app_id, event_id)
        return

    logger.info(
        "CMS processed NGFW event: instance_id=%s (%s->%s) app_id=%s (%s->%s) serial=%s event_id=%s",
        instance_id,
        previous_instance_status,
        status or previous_instance_status,
        app_id,
        previous_app_status,
        status or previous_app_status,
        serial_number or "N/A",
        event_id,
    )
