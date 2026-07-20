"""WebSocket consumers for real-time range and NGFW status updates.

Split out of ``mission_control.consumers`` so that module stays under Sonar
S104's 500-line cap. ``mission_control.consumers`` re-exports these classes, so
``from mission_control.consumers import RangeStatusConsumer, NGFWStatusConsumer``
continues to resolve and the ASGI routing import is unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from shared.channels.payloads import NGFWStatusChannelEvent, RangeStatusChannelEvent
from shared.enums import WebSocketCloseCode
from shared.schemas import RangeRef

logger = logging.getLogger(__name__)


class RangeStatusConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time range status updates.

    Pushes status updates to browser when range lifecycle events occur.
    Uses "hydrate on connect, stream deltas" pattern.

    URL pattern: ws/range-status/<request_id>/
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.request_id: str | None = None
        self.group_name: str | None = None

    async def connect(self) -> None:
        """Handle WebSocket connection - join range group and send initial state."""
        from cms.services import get_range_by_request_id
        from shared.channels.groups import range_event_group
        from shared.exceptions import CMSError

        # Verify authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated WebSocket connection attempt to range status")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

        # Get request_id from URL (UUID string)
        self.request_id = self.scope["url_route"]["kwargs"]["request_id"]
        self.group_name = range_event_group(self.request_id)

        # Verify user owns this range via CMS (handles ownership check)
        try:
            range_instance = await sync_to_async(get_range_by_request_id)(user, self.request_id)
        except CMSError:
            # CMSError covers both not found and permission denied
            logger.warning(
                "Range with request_id %s not found or not owned by user %s",
                self.request_id,
                user.id,
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return

        # Join the range group
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Accept the connection
        await self.accept()

        # Hydrate: send current status immediately
        await self.send(
            text_data=json.dumps(
                {
                    "type": "status",
                    "request_id": self.request_id,
                    "status": range_instance.status,
                }
            )
        )

        logger.info("Range status WebSocket connected for request %s", self.request_id)

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection - leave range group."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            "Range status WebSocket disconnected for request %s (code: %s)",
            self.request_id,
            close_code,
        )

    async def range_status(self, event: RangeStatusChannelEvent) -> None:
        """Handle range status update from channel layer.

        Called when a status update is broadcast to the range group.
        """
        range_ref_payload = event.get("range_ref")
        request_id: str
        status: str
        if range_ref_payload:
            range_ref = RangeRef.model_validate(range_ref_payload)
            request_id = str(range_ref.request_id)
            status = range_ref.status.value
        else:
            request_id = str(event.get("request_id", ""))
            status = str(event.get("new_status", ""))

        await self.send(
            text_data=json.dumps(
                {
                    "type": "status",
                    "request_id": request_id,
                    "status": status,
                    "error_message": event.get("error_message"),
                }
            )
        )


class NGFWStatusConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time NGFW status updates.

    Pushes status updates to browser during NGFW provisioning.
    Uses "hydrate on connect, stream deltas" pattern.
    Designed for long provisioning cycles (up to 40 minutes).

    URL pattern: ws/ngfw-status/<app_id>/
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.app_id: str | None = None
        self.group_name: str | None = None

    async def connect(self) -> None:
        """Handle WebSocket connection - join NGFW group and send initial state."""
        from cms.services import get_ngfw as cms_get_ngfw
        from shared.channels.groups import ngfw_event_group
        from shared.exceptions import CMSError

        # Verify authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated WebSocket connection attempt to NGFW status")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

        # Get app_id from URL (this is the CMS App UUID)
        self.app_id = self.scope["url_route"]["kwargs"]["app_id"]
        self.group_name = ngfw_event_group(self.app_id)

        # Verify user owns this NGFW via CMS (handles ownership check)
        try:
            ngfw = await sync_to_async(cms_get_ngfw)(user, self.app_id)
        except CMSError:
            logger.warning(
                "NGFW app %s not found or not owned by user %s",
                self.app_id,
                user.id,
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return

        # Join the NGFW group
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Accept the connection
        await self.accept()

        # Hydrate: send current status immediately
        await self.send(
            text_data=json.dumps(
                {
                    "type": "status",
                    "app_id": self.app_id,
                    "status": ngfw.status,
                }
            )
        )

        logger.info("NGFW status WebSocket connected for app %s", self.app_id)

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection - leave NGFW group."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            "NGFW status WebSocket disconnected for app %s (code: %s)",
            self.app_id,
            close_code,
        )

    async def ngfw_status(self, event: NGFWStatusChannelEvent) -> None:
        """Handle NGFW status update from channel layer.

        Called when a status update is broadcast to the NGFW group.
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "status",
                    "app_id": event.get("app_id"),
                    "status": event.get("status"),
                    "state": event.get("state"),
                    "serial_number": event.get("serial_number"),
                }
            )
        )
