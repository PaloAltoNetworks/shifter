"""WebSocket consumers for terminal SSH connections and range status updates."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from risk_register.services import audit_session_event
from shared.enums import WebSocketCloseCode

logger = logging.getLogger(__name__)


class SSHConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for SSH terminal connections.

    Bridges browser WebSocket to SSH connection via engine.connect_terminal().

    URL pattern: ws/terminal/<instance_uuid>/
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.instance_uuid: str | None = None
        self.ssh_conn: Any = None
        self._read_task: asyncio.Task[None] | None = None
        self.session_id: str = str(uuid.uuid4())[:8]
        self._user_id: int | None = None

    async def connect(self):
        """Handle WebSocket connection request."""
        try:
            await self._do_connect()
        except Exception:
            logger.exception("Unexpected error in WebSocket connect")
            await self.close(code=WebSocketCloseCode.SERVER_ERROR)

    async def _do_connect(self):
        """Authenticate and establish SSH connection.

        Engine handles all validation: ownership, range status, instance lookup.
        """
        from engine import connect_terminal

        # Get client IP for audit logging
        headers = dict(self.scope.get("headers", []))
        xff = headers.get(b"x-forwarded-for", b"").decode()
        client_ip = xff.split(",")[0].strip() if xff else None

        # 1. Verify authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated terminal connection attempt")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

        self._user_id = user.id

        # 2. Extract instance UUID from URL
        self.instance_uuid = self.scope["url_route"]["kwargs"].get("instance_uuid")
        if not self.instance_uuid:
            logger.warning("Terminal connection without instance_uuid")
            await self.close(code=WebSocketCloseCode.INVALID_REQUEST)
            return

        logger.debug(
            "Terminal connection requested: user_id=%s instance_uuid=%s",
            user.id,
            self.instance_uuid,
        )

        # 3. Establish SSH connection via engine
        # Engine looks up Range by instance_uuid and validates ownership/status
        try:
            self.ssh_conn = await sync_to_async(connect_terminal)(user, self.instance_uuid)
            await self.ssh_conn.connect()
        except PermissionError:
            logger.warning(
                "Terminal connection denied - permission error: uuid=%s",
                self.instance_uuid,
            )
            # Audit log access denied
            await sync_to_async(audit_session_event)(
                action="access_denied",
                user_id=user.id,
                session_id=self.session_id,
                range_id=None,
                session_type="terminal",
                source_ip=client_ip,
                context=f"Permission denied for instance {self.instance_uuid}",
            )
            await self.close(code=WebSocketCloseCode.PERMISSION_DENIED)
            return
        except ValueError as e:
            logger.warning(
                "Terminal connection denied: uuid=%s error=%s",
                self.instance_uuid,
                str(e),
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return
        except Exception as e:
            logger.exception(
                "SSH connection failed: uuid=%s error=%s",
                self.instance_uuid,
                str(e),
            )
            await self.close(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)
            return

        # 4. Accept WebSocket and start reading SSH output
        await self.accept()

        # Audit log successful connection
        await sync_to_async(audit_session_event)(
            action="connect",
            user_id=user.id,
            session_id=self.session_id,
            range_id=None,
            session_type="terminal",
            target_ip=self.instance_uuid,
            source_ip=client_ip,
        )

        logger.info(
            "Terminal connected: user_id=%s uuid=%s",
            user.id,
            self.instance_uuid,
        )

        # Start background task to read SSH output
        self._read_task = asyncio.create_task(self._read_ssh_output())

    async def _read_ssh_output(self):
        """Background task to read SSH output and send to WebSocket."""
        try:
            while self.ssh_conn.is_connected:
                data = await self.ssh_conn.receive()
                if data:
                    # receive() returns bytes, decode to string for JSON
                    output = data.decode("utf-8", errors="replace")
                    await self.send(text_data=json.dumps({"type": "output", "data": output}))
                # Empty bytes just means timeout (no data), keep looping
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error reading SSH output: uuid=%s", self.instance_uuid)
        finally:
            await self.close()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection - cleanup SSH connection."""
        logger.debug(
            "Terminal disconnected: uuid=%s code=%s",
            self.instance_uuid,
            close_code,
        )

        # Cancel read task if running
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task

        # Close SSH connection
        if self.ssh_conn:
            try:
                await self.ssh_conn.disconnect()
            except Exception:
                logger.exception("Error closing SSH connection: uuid=%s", self.instance_uuid)

        # Audit log disconnection if we had a valid session
        if self._user_id:
            await sync_to_async(audit_session_event)(
                action="disconnect",
                user_id=self._user_id,
                session_id=self.session_id,
                session_type="terminal",
                context=f"close_code={close_code}",
            )

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages - forward to SSH."""
        if not self.ssh_conn or not text_data:
            return

        try:
            message = json.loads(text_data)
            msg_type = message.get("type")

            if msg_type == "input":
                data = message.get("data", "")
                # send() expects bytes
                await self.ssh_conn.send(data.encode("utf-8"))

            elif msg_type == "resize":
                cols = message.get("cols", 80)
                rows = message.get("rows", 24)
                await self.ssh_conn.resize(cols, rows)

        except json.JSONDecodeError:
            logger.warning("Invalid JSON from terminal: uuid=%s", self.instance_uuid)
        except Exception:
            logger.exception("Error handling terminal input: uuid=%s", self.instance_uuid)


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

    async def connect(self):
        """Handle WebSocket connection - join range group and send initial state."""
        from cms import get_range_by_request_id
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

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection - leave range group."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            "Range status WebSocket disconnected for request %s (code: %s)",
            self.request_id,
            close_code,
        )

    async def range_status(self, event):
        """Handle range status update from channel layer.

        Called when a status update is broadcast to the range group.
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "status",
                    "request_id": event.get("request_id"),
                    "status": event.get("new_status"),
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

    async def connect(self):
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

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection - leave NGFW group."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            "NGFW status WebSocket disconnected for app %s (code: %s)",
            self.app_id,
            close_code,
        )

    async def ngfw_status(self, event):
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
