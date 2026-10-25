"""The portal's private VPN control API, as seen from one pool server.

Every call carries a fresh Google identity token for the configured audience.
Redirects are refused and responses are bounded, so a misdirected or hostile
endpoint cannot steer the server elsewhere or exhaust it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import transport

_MAX_RESPONSE_BYTES = 65_536
_TIMEOUT = 10


class PortalError(RuntimeError):
    """A control call did not produce the contracted result."""


class PortalUnavailable(PortalError):
    """The portal could not be reached or answered outside its contract."""


class PortalRefused(PortalError):
    """The portal refused the request with a closed reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Grant:
    """The single destination one authorized client may reach."""

    session: str
    target: str
    ports: tuple[int, ...]
    heartbeat_seconds: int


def _is_port(value: object) -> bool:
    """Return whether ``value`` is a TCP/UDP port number (and not a bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def _refusal(status: int, payload: dict[str, object]) -> PortalError:
    """Map a non-success answer to a refusal with its reason code, or to unavailability."""
    if status in (400, 403) and isinstance(payload.get("error"), str):
        return PortalRefused(str(payload["error"]))
    return PortalUnavailable(f"status {status}")


def _grant(payload: dict[str, object]) -> Grant:
    """Validate a grant strictly; anything outside the contract is treated as unavailable."""
    session, target = payload.get("session"), payload.get("target")
    ports, interval = payload.get("ports"), payload.get("heartbeat_seconds")
    if not (
        isinstance(session, str)
        and isinstance(target, str)
        and isinstance(ports, list)
        and ports
        and all(_is_port(port) for port in ports)
        and isinstance(interval, int)
        and not isinstance(interval, bool)
    ):
        raise PortalUnavailable("grant outside the contract")
    return Grant(session=session, target=target, ports=tuple(ports), heartbeat_seconds=interval)


class PortalClient:
    """Authorize, renew and end sessions for this server."""

    def __init__(self, portal_url: str, audience: str, server: str, token: Callable[[str], str]) -> None:
        self._base = f"{portal_url}/api/v1/cms/vpn-control"
        self._audience = audience
        self._server = server
        self._token = token

    def _post(self, path: str, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        """POST one JSON body and return the status and a bounded JSON object."""
        # The https origin is validated at startup; the transport opens http/https only.
        request = urllib.request.Request(  # noqa: S310
            f"{self._base}/{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token(self._audience)}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with transport.OPENER.open(request, timeout=_TIMEOUT) as response:
                status, raw = response.status, response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read(_MAX_RESPONSE_BYTES + 1)
        except OSError as error:
            # URLError and socket timeouts are both OSError subclasses.
            raise PortalUnavailable(type(error).__name__) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise PortalUnavailable("response too large")
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            raise PortalUnavailable("response is not JSON") from None
        if not isinstance(payload, dict):
            raise PortalUnavailable("response is not an object")
        return status, payload

    def authorize(self, common_name: str, client_id: int, client_address: str) -> Grant:
        """Ask whether this verified client may connect; return its single grant."""
        status, payload = self._post(
            "sessions/",
            {
                "common_name": common_name,
                "server": self._server,
                "client_id": client_id,
                "client_address": client_address,
            },
        )
        if status != 201:
            raise _refusal(status, payload)
        return _grant(payload)

    def heartbeat(self, sessions: list[str]) -> tuple[set[str], int]:
        """Renew live sessions; return those to disconnect and the next interval."""
        status, payload = self._post("heartbeat/", {"server": self._server, "sessions": sessions})
        if status != 200:
            raise _refusal(status, payload)
        disconnect = payload.get("disconnect")
        interval = payload.get("heartbeat_seconds")
        if not isinstance(disconnect, list) or not isinstance(interval, int):
            raise PortalUnavailable("heartbeat outside the contract")
        return {str(value) for value in disconnect}, interval

    def end(self, session: str) -> None:
        """Report that a session's client disconnected."""
        status, payload = self._post("sessions/end/", {"server": self._server, "session": session})
        if status != 204:
            raise _refusal(status, payload)
