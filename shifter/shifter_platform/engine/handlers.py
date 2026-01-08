"""Engine handlers for processing SNS/SQS events.

These handlers process range and NGFW status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from engine.models import App, Instance, Range
from shared.enums import ResourceStatus
from shared.messages.events import (
    EVENT_TYPE_NGFW,
    EVENT_TYPE_PROVISIONED,
    EVENT_TYPE_STATUS_UPDATED,
)

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
        _handle_status_updated(event)
    elif event_type == EVENT_TYPE_PROVISIONED:
        _handle_provisioned(event)
    else:
        logger.debug("Ignoring event_type=%s", event_type)


def _handle_status_updated(event: dict) -> None:
    """Handle range.status.updated event - update status and timestamps.

    Args:
        event: Event payload with range_id, user_id, new_status, error_message.
    """
    range_id = event.get("range_id")
    user_id = event.get("user_id")
    new_status = event.get("new_status")
    error_message = event.get("error_message")
    event_id = event.get("event_id", "unknown")

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
        logger.exception("DB error saving Range: range_id=%s", range_id)
        return

    logger.info(
        "Engine updated Range: range_id=%s status=%s->%s event_id=%s",
        range_id,
        previous_status,
        new_status,
        event_id,
    )


def _handle_provisioned(event: dict) -> None:
    """Handle range.provisioned event - update provisioned_instances.

    Merges instance details from provisioner with UUIDs from range_config.
    The provisioner provides: role, os, instance_id, private_ip, ssh_key_secret_arn
    The range_config contains: uuid, role, os_type (from CMS hydration)

    Args:
        event: Event payload with range_id, user_id, instances, subnet_id, etc.
    """
    range_id = event.get("range_id")
    user_id = event.get("user_id")
    instances = event.get("instances", [])
    subnet_id = event.get("subnet_id")
    subnet_cidr = event.get("subnet_cidr")
    pulumi_stack = event.get("pulumi_stack")
    event_id = event.get("event_id", "unknown")

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("Range not found for provisioned event: range_id=%s", range_id)
        return

    if range_obj.user_id != user_id:
        logger.error(
            "user_id mismatch in provisioned event: message=%s, range=%s (range_id=%s)",
            user_id,
            range_obj.user_id,
            range_id,
        )
        return

    # Build UUID lookup from range_config (CMS-provided UUIDs)
    uuid_by_role = {}
    if range_obj.range_config and "instances" in range_obj.range_config:
        for spec in range_obj.range_config["instances"]:
            role = spec.get("role")
            uuid = spec.get("uuid")
            if role and uuid:
                uuid_by_role[role] = uuid

    # Merge provisioner instance data with CMS UUIDs
    provisioned_instances = []
    for inst in instances:
        role = inst.get("role")
        merged = {
            "uuid": uuid_by_role.get(role),  # From CMS
            "role": role,
            "os_type": inst.get("os"),
            "instance_id": inst.get("instance_id"),
            "private_ip": inst.get("private_ip"),
            "ssh_key_secret_arn": inst.get("ssh_key_secret_arn"),
        }
        provisioned_instances.append(merged)

    # Update range with provisioned data
    update_fields = ["provisioned_instances"]
    range_obj.provisioned_instances = provisioned_instances

    if subnet_id:
        range_obj.subnet_id = subnet_id
        update_fields.append("subnet_id")

    if subnet_cidr:
        range_obj.subnet_cidr = subnet_cidr
        update_fields.append("subnet_cidr")

    if pulumi_stack:
        range_obj.pulumi_stack = pulumi_stack
        update_fields.append("pulumi_stack")

    try:
        range_obj.save(update_fields=update_fields)
    except Exception:
        logger.exception("DB error saving provisioned instances: range_id=%s", range_id)
        return

    logger.info(
        "Engine updated provisioned_instances: range_id=%s instances=%d event_id=%s",
        range_id,
        len(provisioned_instances),
        event_id,
    )


# =============================================================================
# NGFW Event Handlers
# =============================================================================


def process_ngfw_event(message: str | dict) -> None:
    """Process unified NGFW event from SNS/SQS.

    Updates both Instance and App models based on the event:
    - Looks up Instance by instance_id (UUID)
    - Looks up App by app_id (UUID)
    - Updates status on both if provided
    - Merges event state into Instance.state

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


def _get_ngfw_models(
    instance_id: str, app_id: str, event_id: str
) -> tuple[Instance, App] | None:
    """Look up Instance and App by UUID, logging warnings if not found."""
    try:
        instance = Instance.objects.get(uuid=instance_id)
    except Instance.DoesNotExist:
        logger.warning(
            "Instance not found: instance_id=%s event_id=%s", instance_id, event_id
        )
        return None

    try:
        app = App.objects.get(uuid=app_id)
    except App.DoesNotExist:
        logger.warning("App not found: app_id=%s event_id=%s", app_id, event_id)
        return None

    return instance, app


def _handle_ngfw_event(event: dict) -> None:
    """Handle unified ngfw.event - update Instance and App.

    Args:
        event: Event payload with request_id, instance_id, app_id, status, state.
    """
    event_id = event.get("event_id", "unknown")
    instance_id = event.get("instance_id")
    app_id = event.get("app_id")
    status = event.get("status")
    state = event.get("state")

    # Validate required fields
    if not instance_id or not app_id:
        logger.warning(
            "NGFW event missing required fields: instance_id=%s app_id=%s event_id=%s",
            instance_id,
            app_id,
            event_id,
        )
        return

    # Look up models
    models = _get_ngfw_models(instance_id, app_id, event_id)
    if not models:
        return
    instance, app = models

    previous_instance_status = instance.status
    previous_app_status = app.status

    # Update Instance
    instance_update_fields = _update_ngfw_instance(instance, status, state)
    if instance_update_fields:
        try:
            instance.save(update_fields=instance_update_fields)
        except Exception:
            logger.exception(
                "DB error saving Instance: instance_id=%s event_id=%s",
                instance_id,
                event_id,
            )
            return

    # Update App
    app_update_fields = _update_ngfw_app(app, status)
    if app_update_fields:
        try:
            app.save(update_fields=app_update_fields)
        except Exception:
            logger.exception(
                "DB error saving App: app_id=%s event_id=%s", app_id, event_id
            )
            return

    logger.info(
        "Engine processed NGFW event: instance_id=%s (%s->%s) app_id=%s (%s->%s) "
        "state_keys=%s event_id=%s",
        instance_id,
        previous_instance_status,
        status or previous_instance_status,
        app_id,
        previous_app_status,
        status or previous_app_status,
        list(state.keys()) if state else [],
        event_id,
    )


def _update_ngfw_instance(
    instance: Instance, status: str | None, state: dict | None
) -> list[str]:
    """Update Instance fields and return list of fields to save."""
    update_fields = []

    if status:
        instance.status = status
        update_fields.append("status")

        if status == ResourceStatus.DESTROYED.value:
            instance.destroyed_at = timezone.now()
            update_fields.append("destroyed_at")

    if state:
        current_state = instance.state or {}
        current_state.update(state)
        instance.state = current_state
        update_fields.append("state")

    return update_fields


def _update_ngfw_app(app: App, status: str | None) -> list[str]:
    """Update App fields and return list of fields to save."""
    update_fields = []

    if status:
        app.status = status
        update_fields.append("status")

        if status == ResourceStatus.DESTROYED.value:
            app.destroyed_at = timezone.now()
            update_fields.append("destroyed_at")

    return update_fields
