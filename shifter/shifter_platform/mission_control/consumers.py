"""WebSocket consumers for terminal SSH connections and NGFW provisioning status."""

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from engine.models import Range
from mission_control.services.secrets import SecretsError, get_ssh_key
from mission_control.services.ssh import SSHConnection, SSHConnectionError

logger = logging.getLogger(__name__)


def get_ssh_username(os_type: str) -> str:
    """Determine SSH username based on OS type.

    Args:
        os_type: Operating system identifier (e.g., 'kali', 'ubuntu', 'windows')

    Returns:
        SSH username for the given OS type
    """
    if os_type.startswith("kali"):
        return "kali"
    elif os_type.startswith("windows"):
        return "Administrator"
    elif os_type.startswith("amazon-linux"):
        return "ec2-user"
    else:
        return "ubuntu"


@dataclass
class ConnectionDetails:
    """SSH connection details for a range instance."""

    host: str
    secret_arn: str
    username: str


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

    def _get_authenticated_user(self):
        """Get authenticated user from scope.

        Returns:
            User object if authenticated, None otherwise.
        """
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            return None
        return user

    def _resolve_connection_details(self, range_obj) -> ConnectionDetails | None:
        """Resolve SSH connection details from range instance.

        Args:
            range_obj: Range model instance with provisioned_instances

        Returns:
            ConnectionDetails if valid, None if instance not found or details missing.
        """
        # Get instance based on type
        if self.instance_type == "kali":
            instance = range_obj.attacker_instance
        else:  # victim
            victims = range_obj.victim_instances
            instance = victims[0] if victims else None

        if not instance:
            logger.error(
                "No %s instance found in range %s provisioned_instances",
                self.instance_type,
                self.range_id,
            )
            return None

        host = instance.get("private_ip")
        secret_arn = instance.get("ssh_key_secret_arn")
        os_type = instance.get("os", "")

        if not host or not secret_arn:
            logger.error(
                "Missing connection details for range %s instance %s: host=%s, secret_arn=%s",
                self.range_id,
                self.instance_type,
                host,
                secret_arn,
            )
            return None

        username = get_ssh_username(os_type)

        return ConnectionDetails(host=host, secret_arn=secret_arn, username=username)

    async def _fetch_authorized_range(self, user):
        """Fetch range and verify user authorization.

        Args:
            user: Authenticated user object

        Returns:
            Range object if authorized, None otherwise (closes with appropriate code).
        """

        try:
            range_obj = await sync_to_async(Range.objects.select_related("user").get)(id=self.range_id)
        except Range.DoesNotExist:
            logger.warning("Range %s not found", self.range_id)
            await self.close(code=4004)
            return None

        if range_obj.user_id != user.id:
            logger.warning(
                "User %s attempted to access range %s owned by %s",
                user.id,
                self.range_id,
                range_obj.user_id,
            )
            await self.close(code=4003)
            return None

        if range_obj.status != Range.Status.READY:
            logger.warning(
                "Attempted to connect to non-ready range %s (status: %s)",
                self.range_id,
                range_obj.status,
            )
            await self.close(code=4004)
            return None

        return range_obj

    async def _retrieve_ssh_key(self, secret_arn: str) -> str | None:
        """Retrieve SSH private key from Secrets Manager.

        Args:
            secret_arn: ARN of the secret containing the SSH key

        Returns:
            Private key string if successful, None otherwise (closes with 4005).
        """
        try:
            return await asyncio.get_event_loop().run_in_executor(None, get_ssh_key, secret_arn)
        except SecretsError:
            logger.exception("Failed to retrieve SSH key for range %s", self.range_id)
            await self.close(code=4005)
            return None

    async def _establish_ssh_connection(self, details: ConnectionDetails, private_key: str) -> bool:
        """Establish SSH connection to the instance.

        Args:
            details: Connection details (host, username)
            private_key: SSH private key

        Returns:
            True if connection established, False otherwise (closes with 4006).
        """
        try:
            self.ssh_connection = SSHConnection(
                host=details.host,
                username=details.username,
                private_key=private_key,
            )
            await self.ssh_connection.connect()
            return True
        except SSHConnectionError:
            logger.exception(
                "SSH connection failed for range %s instance %s",
                self.range_id,
                self.instance_type,
            )
            await self.close(code=4006)
            return False

    async def connect(self):
        """Handle WebSocket connection request."""
        try:
            await self._do_connect()
        except Exception:
            logger.exception("Unexpected error in WebSocket connect")
            await self.close(code=4500)

    async def _do_connect(self):
        """Internal connect logic - orchestrates the connection process.

        Each step delegates to a focused helper method that handles its own
        error logging and WebSocket close codes.
        """
        # Step 1: Verify authentication
        user = self._get_authenticated_user()
        if not user:
            logger.warning("Unauthenticated WebSocket connection attempt")
            await self.close(code=4001)
            return

        # Step 2: Parse URL parameters
        self.range_id = int(self.scope["url_route"]["kwargs"]["range_id"])
        self.instance_type = self.scope["url_route"]["kwargs"]["instance"]

        # Step 3: Fetch and authorize range
        range_obj = await self._fetch_authorized_range(user)
        if not range_obj:
            return

        # Step 4: Resolve connection details
        details = self._resolve_connection_details(range_obj)
        if not details:
            await self.close(code=4005)
            return

        # Step 5: Retrieve SSH key
        private_key = await self._retrieve_ssh_key(details.secret_arn)
        if not private_key:
            return

        # Step 6: Establish SSH connection
        if not await self._establish_ssh_connection(details, private_key):
            return

        # Step 7: Accept WebSocket and start output task
        await self.accept()
        logger.info(
            "Terminal WebSocket connected for range %s instance %s",
            self.range_id,
            self.instance_type,
        )
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
