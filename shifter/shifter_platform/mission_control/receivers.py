"""Mission Control signal receivers for engine events.

These receivers replace the SQS worker handler (mission_control.handlers.process_event).
They connect to Django signals emitted by the engine provisioner and broadcast
updates to WebSocket clients via Django Channels.
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.dispatch import receiver

from engine.signals import ngfw_status_changed, range_status_changed
from shared.channels.groups import ngfw_event_group, range_event_group

logger = logging.getLogger(__name__)


@receiver(range_status_changed)
def on_range_status_changed(sender, **kwargs) -> None:
    """Broadcast range status change to WebSocket clients.

    Replaces mission_control.handlers.process_range_event.
    """
    request_id = kwargs.get("request_id")
    new_status = kwargs.get("new_status")
    error_message = kwargs.get("error_message")

    if not request_id:
        logger.error("on_range_status_changed: missing request_id")
        return

    channel_layer = get_channel_layer()
    group_name = range_event_group(str(request_id))

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "range.status",
            "request_id": str(request_id),
            "new_status": new_status,
            "error_message": error_message,
        },
    )

    logger.info(
        "MC broadcast to group %s: request_id=%s status=%s",
        group_name,
        request_id,
        new_status,
    )


@receiver(ngfw_status_changed)
def on_ngfw_status_changed(sender, **kwargs) -> None:
    """Broadcast NGFW status change to WebSocket clients.

    Replaces mission_control.handlers.process_ngfw_event.
    """
    app_id = kwargs.get("app_id")
    status = kwargs.get("status")
    serial_number = kwargs.get("serial_number")

    if not app_id or not isinstance(app_id, str):
        logger.warning("on_ngfw_status_changed: invalid app_id=%s", app_id)
        return

    channel_layer = get_channel_layer()
    group_name = ngfw_event_group(app_id)

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "ngfw.status",
            "app_id": app_id,
            "status": status,
            "state": {},
            "serial_number": serial_number,
        },
    )

    logger.info(
        "MC broadcast to group %s: app_id=%s status=%s",
        group_name,
        app_id,
        status,
    )
