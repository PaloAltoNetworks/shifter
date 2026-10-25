"""OpenVPN management interface over a local unix socket (management-notes.txt).

With ``--management-client-auth`` OpenVPN verifies the client certificate, then
announces each connection as a ``>CLIENT:CONNECT`` block and waits for the
controller to answer ``client-auth`` or ``client-deny``. ``ESTABLISHED`` carries
the client's tunnel address and ``DISCONNECT`` its departure.

One reader thread owns the socket input: notification blocks go to the event
queue, command replies (``SUCCESS:``/``ERROR:``) to the reply queue. Commands
are serialized, so each reply belongs to the command that is waiting for it.
"""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass, field

_REPLY_TIMEOUT = 10


class ManagementError(RuntimeError):
    """The management interface refused a command or went away."""


_CLIENT = ">CLIENT:"
_CLIENT_ENV = ">CLIENT:ENV,"


@dataclass(frozen=True)
class ClientEvent:
    """One ``>CLIENT:`` notification with its environment."""

    kind: str
    cid: int
    kid: int | None = None
    env: dict[str, str] = field(default_factory=dict)


def parse_event_header(line: str) -> tuple[str, int, int | None] | None:
    """Parse ``>CLIENT:KIND,CID[,KID]``; return None for anything else."""
    if not line.startswith(_CLIENT) or line.startswith(_CLIENT_ENV):
        return None
    kind, _, rest = line[len(_CLIENT) :].partition(",")
    parts = rest.split(",")
    try:
        cid = int(parts[0])
        kid = int(parts[1]) if len(parts) > 1 and kind in {"CONNECT", "REAUTH"} else None
    except (ValueError, IndexError):
        return None
    return kind, cid, kid


def _quote(text: str) -> str:
    """Quote a reason string for the management command line."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Management:
    """A connected management client."""

    def __init__(self, path: str) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.connect(path)
        self._file = self._socket.makefile("rw", encoding="utf-8", newline="\n")
        self.events: queue.Queue[ClientEvent | None] = queue.Queue()
        self._replies: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, name="management-reader", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        pending: tuple[str, int, int | None] | None = None
        env: dict[str, str] = {}
        for raw in self._file:
            line = raw.rstrip("\r\n")
            header = parse_event_header(line)
            if header is not None:
                pending, env = header, {}
            elif line.startswith(_CLIENT_ENV) and pending is not None:
                entry = line[len(_CLIENT_ENV) :]
                if entry == "END":
                    kind, cid, kid = pending
                    self.events.put(ClientEvent(kind=kind, cid=cid, kid=kid, env=env))
                    pending = None
                else:
                    key, _, value = entry.partition("=")
                    env[key] = value
            elif line.startswith(("SUCCESS:", "ERROR:")):
                self._replies.put(line)
        # The socket closed: tell the consumer there will be no more events.
        self.events.put(None)

    def _command(self, *lines: str) -> str:
        with self._lock:
            for line in lines:
                self._file.write(line + "\n")
            self._file.flush()
            try:
                reply = self._replies.get(timeout=_REPLY_TIMEOUT)
            except queue.Empty:
                raise ManagementError("no reply from OpenVPN") from None
        if reply.startswith("ERROR:"):
            raise ManagementError(reply)
        return reply

    def allow(self, cid: int, kid: int, config_lines: list[str]) -> None:
        """Admit a pending client with per-client configuration (for example its route)."""
        self._command(f"client-auth {cid} {kid}", *config_lines, "END")

    def allow_unchanged(self, cid: int, kid: int) -> None:
        """Admit a renegotiating client without new configuration."""
        self._command(f"client-auth-nt {cid} {kid}")

    def deny(self, cid: int, kid: int, reason: str) -> None:
        """Refuse a pending client; the reason is logged by OpenVPN, not sent to the client."""
        self._command(f"client-deny {cid} {kid} {_quote(reason)}")

    def kill(self, cid: int) -> None:
        """Disconnect a client."""
        self._command(f"client-kill {cid}")
