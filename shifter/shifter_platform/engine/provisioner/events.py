"""Event publishing for Shifter Engine provisioner.

Emits Django signals instead of publishing to SNS/SQS.
Signal receivers in cms and mission_control handle their respective concerns.

The public API is unchanged from the original SNS-based implementation:
    publish_status_update, publish_ready, publish_failed, publish_destroyed,
    publish_cancelled, publish_ngfw_event
"""

from __future__ import annotations

import logging

from engine.signals import ngfw_status_changed, range_provisioned, range_status_changed

logger = logging.getLogger(__name__)

# Resource status constants (matching shared.enums.ResourceStatus)
STATUS_PENDING = "pending"
STATUS_PROVISIONING = "provisioning"
STATUS_AWAITING_ASSOCIATION = "awaiting_association"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DESTROYING = "destroying"
STATUS_DESTROYED = "destroyed"


def publish_status_update(
    request_id: str,
    range_id: int,
    user_id: int,
    new_status: str,
    error_message: str | None = None,
) -> None:
    """Emit range_status_changed signal."""
    logger.info(
        "Emitting range_status_changed: request_id=%s range_id=%s new_status=%s",
        request_id,
        range_id,
        new_status,
    )

    range_status_changed.send(
        sender=None,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=new_status,
        error_message=error_message,
    )


def publish_ready(
    request_id: str,
    range_id: int,
    user_id: int,
) -> None:
    """Emit status update (ready) + range_provisioned signal."""
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_READY,
    )

    range_provisioned.send(
        sender=None,
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
    )

    logger.info(
        "Emitting range_provisioned: request_id=%s range_id=%s",
        request_id,
        range_id,
    )


def publish_failed(
    request_id: str,
    range_id: int,
    user_id: int,
    error_message: str,
) -> None:
    """Emit status update with failed status."""
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_FAILED,
        error_message=error_message,
    )


def publish_destroyed(request_id: str, range_id: int, user_id: int) -> None:
    """Emit status update with destroyed status."""
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_DESTROYED,
    )


def publish_cancelled(request_id: str, range_id: int, user_id: int) -> None:
    """Emit status update with destroying status (cancel triggers destroy)."""
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status=STATUS_DESTROYING,
    )


def publish_ngfw_event(
    request_id: str,
    instance_id: str,
    app_id: str | None,
    status: str,
    serial_number: str | None = None,
) -> None:
    """Emit ngfw_status_changed signal."""
    logger.info(
        "Emitting ngfw_status_changed: request_id=%s instance_id=%s app_id=%s status=%s serial=%s",
        request_id,
        instance_id,
        app_id,
        status,
        serial_number or "N/A",
    )

    ngfw_status_changed.send(
        sender=None,
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=status,
        serial_number=serial_number,
    )
