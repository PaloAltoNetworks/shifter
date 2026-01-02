"""SSH connection service using asyncssh."""

import asyncio
import logging

import asyncssh

logger = logging.getLogger(__name__)


class SSHConnectionError(Exception):
    """Error establishing or maintaining SSH connection."""

    pass


class SSHConnection:
    """
    Manages an async SSH connection for terminal access.

    Usage:
        async with SSHConnection(host, username, private_key) as conn:
            await conn.send("ls -la\n")
            output = await conn.receive()
    """

    def __init__(
        self,
        host: str,
        username: str,
        private_key: str,
        port: int = 22,
        term_type: str = "xterm-256color",
        term_size: tuple[int, int] = (80, 24),
    ):
        """
        Initialize SSH connection parameters.

        Args:
            host: SSH server hostname or IP
            username: SSH username
            private_key: PEM-encoded private key string
            port: SSH port (default: 22)
            term_type: Terminal type for PTY (default: xterm-256color)
            term_size: Terminal size as (columns, rows)
        """
        self.host = host
        self.username = username
        self.private_key = private_key
        self.port = port
        self.term_type = term_type
        self.term_size = term_size

        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None

    async def connect(self) -> None:
        """Establish SSH connection and start interactive shell."""
        try:
            # Parse the private key
            key = asyncssh.import_private_key(self.private_key)

            # Connect to SSH server
            self._conn = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                client_keys=[key],
                known_hosts=None,  # Accept any host key (internal network)
            )

            # Start interactive shell with PTY
            self._process = await self._conn.create_process(
                term_type=self.term_type,
                term_size=self.term_size,
                encoding=None,  # Binary mode for raw terminal data
            )

            logger.info("SSH connection established to %s@%s:%d", self.username, self.host, self.port)

        except asyncssh.PermissionDenied as e:
            logger.exception("SSH permission denied for %s@%s", self.username, self.host)
            raise SSHConnectionError("SSH authentication failed") from e
        except asyncssh.DisconnectError as e:
            logger.exception("SSH disconnect error connecting to %s", self.host)
            raise SSHConnectionError(f"SSH connection failed: {e}") from e
        except asyncssh.KeyImportError as e:
            logger.exception("Invalid SSH key format for %s@%s", self.username, self.host)
            raise SSHConnectionError("Invalid SSH key format") from e
        except OSError as e:
            logger.exception("Network error connecting to %s", self.host)
            raise SSHConnectionError(f"Network error: {e}") from e
        except Exception as e:
            logger.exception("Unexpected error connecting to %s", self.host)
            raise SSHConnectionError(f"Connection failed: {e}") from e

    async def disconnect(self) -> None:
        """Close SSH connection cleanly."""
        try:
            if self._process:
                self._process.close()
                self._process = None
            if self._conn:
                self._conn.close()
                await self._conn.wait_closed()
                self._conn = None
            logger.info("SSH connection closed to %s", self.host)
        except Exception:
            logger.exception("Error closing SSH connection to %s", self.host)
            # Ensure we clear references even on error
            self._process = None
            self._conn = None

    async def send(self, data: bytes) -> None:
        """
        Send data to the SSH session.

        Args:
            data: Raw bytes to send (terminal input)
        """
        if not self._process:
            raise SSHConnectionError("Not connected")
        self._process.stdin.write(data)

    async def receive(self, timeout: float = 0.1) -> bytes:
        """
        Receive data from the SSH session.

        Args:
            timeout: Max time to wait for data (seconds)

        Returns:
            Raw bytes from terminal output, or empty bytes if no data
        """
        if not self._process:
            raise SSHConnectionError("Not connected")

        try:
            data = await asyncio.wait_for(self._process.stdout.read(4096), timeout=timeout)
            return data if data else b""
        except TimeoutError:
            return b""
        except asyncssh.BreakReceived:
            return b""

    async def resize(self, cols: int, rows: int) -> None:
        """
        Resize the terminal.

        Args:
            cols: Number of columns
            rows: Number of rows
        """
        if self._process:
            self._process.change_terminal_size(cols, rows)
            self.term_size = (cols, rows)

    @property
    def is_connected(self) -> bool:
        """Return True if connection is active."""
        return self._conn is not None and not self._conn.is_closed()

    async def __aenter__(self) -> "SSHConnection":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
