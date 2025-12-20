"""WebSocket consumers for terminal SSH connections."""

import asyncio
import contextlib
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from mission_control.models import Range
from mission_control.services.secrets import SecretsError, get_ssh_key
from mission_control.services.ssh import SSHConnection, SSHConnectionError

logger = logging.getLogger(__name__)


class SSHConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for SSH terminal connections.

    Handles bidirectional communication between browser terminal (xterm.js)
    and remote SSH session (Kali or Victim instance).

    URL pattern: ws/terminal/<range_id>/<instance>/
    where instance is 'kali' or 'victim'
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ssh_connection: SSHConnection | None = None
        self.output_task: asyncio.Task | None = None
        self.range_id: int | None = None
        self.instance_type: str | None = None

    async def connect(self):
        """Handle WebSocket connection request."""
        try:
            await self._do_connect()
        except Exception:
            logger.exception("Unexpected error in WebSocket connect")
            await self.close(code=4500)

    async def _do_connect(self):
        """Internal connect logic - separated for clean exception handling."""
        # Check authentication
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            logger.warning("Unauthenticated WebSocket connection attempt")
            await self.close(code=4001)
            return

        # Get URL parameters
        self.range_id = int(self.scope["url_route"]["kwargs"]["range_id"])
        self.instance_type = self.scope["url_route"]["kwargs"]["instance"]

        # Verify user owns the range and it's ready
        try:
            from asgiref.sync import sync_to_async

            range_obj = await sync_to_async(Range.objects.select_related("user").get)(id=self.range_id)

            if range_obj.user_id != user.id:
                logger.warning(
                    "User %s attempted to access range %s owned by %s",
                    user.id,
                    self.range_id,
                    range_obj.user_id,
                )
                await self.close(code=4003)
                return

            if range_obj.status != Range.Status.READY:
                logger.warning(
                    "Attempted to connect to non-ready range %s (status: %s)",
                    self.range_id,
                    range_obj.status,
                )
                await self.close(code=4004)
                return

            # Get connection details
            if self.instance_type == "kali":
                host = range_obj.kali_ip
                secret_arn = range_obj.kali_ssh_key_secret_arn
                username = "kali"
            else:  # victim
                host = range_obj.victim_ip
                secret_arn = range_obj.victim_ssh_key_secret_arn
                username = "ubuntu"  # Victim uses Ubuntu

            if not host or not secret_arn:
                logger.error(
                    "Missing connection details for range %s instance %s",
                    self.range_id,
                    self.instance_type,
                )
                await self.close(code=4005)
                return

        except Range.DoesNotExist:
            logger.warning("Range %s not found", self.range_id)
            await self.close(code=4004)
            return

        # Get SSH key from Secrets Manager
        try:
            private_key = await asyncio.get_event_loop().run_in_executor(None, get_ssh_key, secret_arn)
        except SecretsError:
            logger.exception("Failed to retrieve SSH key for range %s", self.range_id)
            await self.close(code=4005)
            return

        # Establish SSH connection
        try:
            self.ssh_connection = SSHConnection(
                host=str(host),
                username=username,
                private_key=private_key,
            )
            await self.ssh_connection.connect()
        except SSHConnectionError:
            logger.exception(
                "SSH connection failed for range %s instance %s",
                self.range_id,
                self.instance_type,
            )
            await self.close(code=4006)
            return

        # Accept the WebSocket connection
        await self.accept()
        logger.info(
            "Terminal WebSocket connected for range %s instance %s",
            self.range_id,
            self.instance_type,
        )

        # Start reading SSH output
        self.output_task = asyncio.create_task(self._read_ssh_output())

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        try:
            # Cancel output reading task
            if self.output_task:
                self.output_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.output_task

            # Close SSH connection
            if self.ssh_connection:
                await self.ssh_connection.disconnect()

            logger.info(
                "Terminal WebSocket disconnected for range %s instance %s (code: %s)",
                self.range_id,
                self.instance_type,
                close_code,
            )
        except Exception:
            logger.exception("Error during WebSocket disconnect cleanup")

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages."""
        try:
            await self._do_receive(text_data, bytes_data)
        except Exception:
            logger.exception("Unexpected error in WebSocket receive")

    async def _do_receive(self, text_data=None, bytes_data=None):
        """Internal receive logic - separated for clean exception handling."""
        if text_data:
            try:
                message = json.loads(text_data)
                msg_type = message.get("type")

                if msg_type == "input":
                    # Terminal input - send to SSH
                    data = message.get("data", "")
                    if self.ssh_connection and data:
                        await self.ssh_connection.send(data.encode("utf-8"))

                elif msg_type == "resize":
                    # Terminal resize
                    cols = message.get("cols", 80)
                    rows = message.get("rows", 24)
                    if self.ssh_connection:
                        await self.ssh_connection.resize(cols, rows)

            except json.JSONDecodeError:
                logger.warning("Invalid JSON received on WebSocket")

    async def _read_ssh_output(self):
        """Continuously read SSH output and send to WebSocket."""
        try:
            while self.ssh_connection and self.ssh_connection.is_connected:
                try:
                    data = await self.ssh_connection.receive(timeout=0.1)
                    if data:
                        output = data.decode("utf-8", errors="replace")
                        await self.send(text_data=json.dumps({"type": "output", "data": output}))
                except SSHConnectionError:
                    logger.info(
                        "SSH connection lost for range %s instance %s",
                        self.range_id,
                        self.instance_type,
                    )
                    await self.close(code=4006)
                    break
        except asyncio.CancelledError:
            logger.debug("SSH output task cancelled for range %s", self.range_id)
            raise
        except Exception:
            logger.exception("Unexpected error reading SSH output")
            await self.close(code=4500)
