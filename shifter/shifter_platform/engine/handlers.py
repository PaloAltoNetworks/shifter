"""Engine handlers for processing SNS/SQS range events.

These handlers process range status updates from the Shifter Engine provisioner.
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from engine.models import Range
from shared.enums import RangeStatus
from shared.messages.events import EVENT_TYPE_PROVISIONED, EVENT_TYPE_STATUS_UPDATED

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
        "Engine updated provisioned_instances: range_id=%s instances=%d",
        range_id,
        len(provisioned_instances),
    )
