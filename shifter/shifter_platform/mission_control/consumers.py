"""WebSocket consumers for terminal SSH connections and range status updates."""

import asyncio
import contextlib
import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from engine.models import Range
from shared.enums import WebSocketCloseCode

logger = logging.getLogger(__name__)


class SSHConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for SSH terminal connections.

    Bridges browser WebSocket to SSH connection via engine.connect_terminal().

    URL pattern: ws/terminal/<instance_uuid>/
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_uuid: str | None = None
        self.range_id: int | None = None
        self.ssh_conn = None
        self._read_task = None

    async def connect(self):
        """Handle WebSocket connection request."""
        try:
            await self._do_connect()
        except Exception:
            logger.exception("Unexpected error in WebSocket connect")
            await self.close(code=WebSocketCloseCode.SERVER_ERROR)

    async def _do_connect(self):
        """Authenticate, verify ownership, establish SSH connection."""
        from engine import connect_terminal

        # 1. Verify authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated terminal connection attempt")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

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

        # 3. Get user's active range
        range_obj = await sync_to_async(Range.get_active_for_user)(user)
        if not range_obj:
            logger.warning(
                "Terminal connection denied - no active range: user_id=%s",
                user.id,
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return

        # 4. Verify range is ready
        if range_obj.status != Range.Status.READY:
            logger.warning(
                "Terminal connection denied - range not ready: range_id=%s status=%s",
                range_obj.id,
                range_obj.status,
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return

        self.range_id = range_obj.id

        # 5. Verify instance exists in this range
        instance = await sync_to_async(range_obj.get_instance_by_uuid)(self.instance_uuid)
        if not instance:
            logger.warning(
                "Terminal connection denied - instance not found: range_id=%s uuid=%s",
                self.range_id,
                self.instance_uuid,
            )
            await self.close(code=WebSocketCloseCode.NOT_FOUND)
            return

        # 6. Establish SSH connection
        try:
            self.ssh_conn = await sync_to_async(connect_terminal)(user, self.range_id, self.instance_uuid)
            await self.ssh_conn.connect()
        except PermissionError:
            logger.warning(
                "Terminal connection denied - permission error: range_id=%s uuid=%s",
                self.range_id,
                self.instance_uuid,
            )
            await self.close(code=WebSocketCloseCode.PERMISSION_DENIED)
            return
        except Exception as e:
            logger.exception(
                "SSH connection failed: range_id=%s uuid=%s error=%s",
                self.range_id,
                self.instance_uuid,
                str(e),
            )
            await self.close(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)
            return

        # 7. Accept WebSocket and start reading SSH output
        await self.accept()
        logger.info(
            "Terminal connected: user_id=%s range_id=%s uuid=%s",
            user.id,
            self.range_id,
            self.instance_uuid,
        )

        # Start background task to read SSH output
        self._read_task = asyncio.create_task(self._read_ssh_output())

    async def _read_ssh_output(self):
        """Background task to read SSH output and send to WebSocket."""
        try:
            while True:
                data = await self.ssh_conn.read()
                if data:
                    await self.send(text_data=json.dumps({"type": "output", "data": data}))
                else:
                    break
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
                await self.ssh_conn.close()
            except Exception:
                logger.exception("Error closing SSH connection: uuid=%s", self.instance_uuid)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages - forward to SSH."""
        if not self.ssh_conn or not text_data:
            return

        try:
            message = json.loads(text_data)
            msg_type = message.get("type")

            if msg_type == "input":
                data = message.get("data", "")
                await self.ssh_conn.write(data)

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

    URL pattern: ws/range-status/<range_id>/
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.range_id: int | None = None
        self.group_name: str | None = None

    async def connect(self):
        """Handle WebSocket connection - join range group and send initial state."""
        from shared.channels.groups import range_event_group

        # Verify authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated WebSocket connection attempt to range status")
            await self.close(code=WebSocketCloseCode.NOT_AUTHENTICATED)
            return

        # Get range_id from URL
        self.range_id = int(self.scope["url_route"]["kwargs"]["range_id"])
        self.group_name = range_event_group(self.range_id)

        # Verify user owns this range
        try:
            range_obj = await sync_to_async(Range.objects.get)(id=self.range_id)
            if range_obj.user_id != user.id:
                logger.warning(
                    "User %s attempted to subscribe to range %s owned by %s",
                    user.id,
                    self.range_id,
                    range_obj.user_id,
                )
                await self.close(code=WebSocketCloseCode.PERMISSION_DENIED)
                return
        except Range.DoesNotExist:
            logger.warning("Range %s not found for status subscription", self.range_id)
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
                    "range_id": self.range_id,
                    "status": range_obj.status,
                }
            )
        )

        logger.info("Range status WebSocket connected for range %s", self.range_id)

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection - leave range group."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        logger.info(
            "Range status WebSocket disconnected for range %s (code: %s)",
            self.range_id,
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
                    "range_id": event.get("range_id"),
                    "status": event.get("new_status"),
                    "error_message": event.get("error_message"),
                }
            )
        )
