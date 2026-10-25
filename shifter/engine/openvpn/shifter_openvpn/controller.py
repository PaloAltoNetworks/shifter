"""Authorize, track and revoke the clients of one pool server.

* CONNECT: ask the portal; admit with a route to the single granted target, or
  refuse. A portal that cannot answer means refuse.
* ESTABLISHED: allow the client's tunnel address to the target's ports only.
* DISCONNECT: remove the allowance and tell the portal.
* Heartbeat: report live sessions; disconnect every session the portal returns.
  When the portal cannot be reached for longer than the grace period, every
  session ends: revocation that cannot be confirmed is not assumed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from .management import ClientEvent
from .portal import Grant, PortalRefused, PortalUnavailable

RETRY_SECONDS = 5
_LOGGER = logging.getLogger("shifter_openvpn")


class ManagementPort(Protocol):
    """The OpenVPN management commands the policy issues."""

    def allow(self, cid: int, kid: int, config_lines: list[str]) -> None: ...
    def allow_unchanged(self, cid: int, kid: int) -> None: ...
    def deny(self, cid: int, kid: int, reason: str) -> None: ...
    def kill(self, cid: int) -> None: ...


class PortalPort(Protocol):
    """The portal's session decisions."""

    def authorize(self, common_name: str, client_id: int, client_address: str) -> Grant: ...
    def heartbeat(self, sessions: list[str]) -> tuple[set[str], int]: ...
    def end(self, session: str) -> None: ...


class FirewallPort(Protocol):
    """Per-client forwarding allowances."""

    def allow(self, client: str, target: str, ports: tuple[int, ...]) -> None: ...
    def revoke(self, client: str, target: str, ports: tuple[int, ...]) -> None: ...


@dataclass
class Session:
    """One admitted client and what it may reach."""

    session_id: str
    target: str
    ports: tuple[int, ...]
    address: str | None = None


class Controller:
    """The server-side policy for every client of this OpenVPN process."""

    def __init__(
        self,
        management: ManagementPort,
        portal: PortalPort,
        firewall: FirewallPort,
        *,
        grace_seconds: int = 90,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._management = management
        self._portal = portal
        self._firewall = firewall
        self._grace = grace_seconds
        self._clock = clock
        self._log = log or _LOGGER.info
        self._lock = threading.Lock()
        self._sessions: dict[int, Session] = {}
        self._last_heartbeat = clock()
        self._authorizers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="authorize")

    def handle(self, event: ClientEvent) -> None:
        """Dispatch one management notification; authorization runs off the event thread."""
        if event.kind == "CONNECT":
            self._authorizers.submit(self._connect, event)
        elif event.kind == "REAUTH":
            self._reauth(event)
        elif event.kind == "ESTABLISHED":
            self._established(event)
        elif event.kind == "DISCONNECT":
            self._disconnect(event)

    def _connect(self, event: ClientEvent) -> None:
        kid = event.kid if event.kid is not None else 0
        try:
            grant = self._portal.authorize(
                event.env.get("common_name", ""), event.cid, event.env.get("untrusted_ip", "")
            )
        except PortalRefused as refused:
            self._log(f"deny cid={event.cid} reason={refused.code}")
            self._management.deny(event.cid, kid, refused.code)
            return
        except PortalUnavailable as unavailable:
            self._log(f"deny cid={event.cid} reason=portal-unavailable ({unavailable})")
            self._management.deny(event.cid, kid, "portal unavailable")
            return
        with self._lock:
            self._sessions[event.cid] = Session(grant.session, grant.target, grant.ports)
        self._log(f"allow cid={event.cid} session={grant.session} target={grant.target} ports={list(grant.ports)}")
        self._management.allow(event.cid, kid, [f'push "route {grant.target} 255.255.255.255"'])

    def _reauth(self, event: ClientEvent) -> None:
        kid = event.kid if event.kid is not None else 0
        with self._lock:
            known = event.cid in self._sessions
        # A renegotiating client keeps its session; the heartbeat decides whether it may.
        if known:
            self._management.allow_unchanged(event.cid, kid)
        else:
            self._management.deny(event.cid, kid, "unknown session")

    def _established(self, event: ClientEvent) -> None:
        address = event.env.get("ifconfig_pool_remote_ip", "")
        with self._lock:
            session = self._sessions.get(event.cid)
        if session is None or not address:
            self._management.kill(event.cid)
            return
        try:
            self._firewall.allow(address, session.target, session.ports)
        except Exception as error:
            # An allowance that cannot be installed is a session that cannot work.
            self._log(f"kill cid={event.cid} reason=firewall ({type(error).__name__})")
            self._management.kill(event.cid)
            return
        with self._lock:
            session.address = address

    def _disconnect(self, event: ClientEvent) -> None:
        with self._lock:
            session = self._sessions.pop(event.cid, None)
        if session is None:
            return
        if session.address:
            try:
                self._firewall.revoke(session.address, session.target, session.ports)
            except Exception as error:
                self._log(f"revoke failed cid={event.cid} ({type(error).__name__})")
        try:
            self._portal.end(session.session_id)
        except (PortalRefused, PortalUnavailable) as error:
            self._log(f"end not recorded session={session.session_id} ({error}); the heartbeat reconciles it")
        self._log(f"disconnect cid={event.cid} session={session.session_id}")

    def _kill(self, cid: int, reason: str) -> None:
        self._log(f"kill cid={cid} reason={reason}")
        try:
            self._management.kill(cid)
        except Exception as error:
            self._log(f"kill failed cid={cid} ({type(error).__name__})")

    def heartbeat(self) -> int:
        """Renew live sessions, apply revocations, and return the seconds until the next beat."""
        with self._lock:
            live = {cid: session.session_id for cid, session in self._sessions.items()}
        try:
            disconnect, interval = self._portal.heartbeat(sorted(live.values()))
        except (PortalRefused, PortalUnavailable) as error:
            silent = self._clock() - self._last_heartbeat
            self._log(f"heartbeat failed ({error}); {silent:.0f}s since the last confirmation")
            if silent > self._grace:
                for cid in live:
                    self._kill(cid, "revocation-unconfirmed")
            return RETRY_SECONDS
        self._last_heartbeat = self._clock()
        for cid, session in live.items():
            if session in disconnect:
                self._kill(cid, "revoked")
        return max(RETRY_SECONDS, interval)

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)
