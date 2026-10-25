"""Real public-path Guacamole display-sync and sustained-hold gate (#1816)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass

import websockets
from range_functional_smoke import guacamole, targets
from range_functional_smoke.profile import Protocol

from event_load_harness.auth import Actor
from event_load_harness.results import RouteResult
from event_load_harness.runner import ramp_delays
from event_load_harness.stats import Aggregator


@dataclass(frozen=True)
class TunnelHoldResult:
    ready: bool
    display_synchronized: bool
    held_seconds: float
    synchronized_after_seconds: float | None = None
    error_category: str | None = None


class TunnelHoldCoordinator:
    """Start one shared hold deadline only after every tunnel has synchronized."""

    def __init__(self, participants: int, hold_seconds: float) -> None:
        if participants <= 0:
            raise ValueError("participants must be positive")
        if hold_seconds < 0:
            raise ValueError("hold_seconds must be non-negative")
        self.participants = participants
        self.hold_seconds = hold_seconds
        self._synchronized: set[str] = set()
        self._deadline: float | None = None
        self._failure: str | None = None
        self._lock = asyncio.Lock()

    @property
    def deadline(self) -> float | None:
        return self._deadline

    @property
    def failure(self) -> str | None:
        return self._failure

    async def mark_synchronized(self, participant_id: str) -> None:
        async with self._lock:
            if self._failure is not None:
                return
            self._synchronized.add(participant_id)
            if len(self._synchronized) == self.participants and self._deadline is None:
                self._deadline = time.monotonic() + self.hold_seconds

    async def fail(self, category: str) -> None:
        async with self._lock:
            if self._failure is None:
                self._failure = category


async def _failed_hold(
    category: str,
    coordinator: TunnelHoldCoordinator | None,
    *,
    ready: bool,
    synchronized_at: float | None,
) -> TunnelHoldResult:
    if coordinator is not None:
        await coordinator.fail(category)
    held = 0.0 if synchronized_at is None else time.monotonic() - synchronized_at
    return TunnelHoldResult(ready, synchronized_at is not None, held, error_category=category)


async def _hold_boundary_result(
    *,
    coordinator: TunnelHoldCoordinator | None,
    ready: bool,
    synchronized_at: float | None,
    started: float,
    now: float,
    synchronization_deadline: float,
    hold_seconds: float,
) -> TunnelHoldResult | None:
    if coordinator is not None and coordinator.failure is not None:
        held = 0.0 if synchronized_at is None else now - synchronized_at
        return TunnelHoldResult(ready, synchronized_at is not None, held, error_category="peer_failed")
    if synchronized_at is None and now >= synchronization_deadline:
        return await _failed_hold("synchronization_timeout", coordinator, ready=ready, synchronized_at=synchronized_at)
    deadline = coordinator.deadline if coordinator is not None else None
    hold_complete = deadline is not None and now >= deadline
    if coordinator is None:
        hold_complete = synchronized_at is not None and now - synchronized_at >= hold_seconds
    if not hold_complete or synchronized_at is None:
        return None
    return TunnelHoldResult(
        ready=True,
        display_synchronized=True,
        held_seconds=now - synchronized_at,
        synchronized_after_seconds=synchronized_at - started,
    )


async def consume_tunnel_until_hold(
    socket,
    *,
    hold_seconds: float,
    recv_timeout: float = 5.0,
    synchronization_timeout: float = 60.0,
    coordinator: TunnelHoldCoordinator | None = None,
    participant_id: str | None = None,
) -> TunnelHoldResult:
    """Continuously parse the tunnel and acknowledge sync instructions for the hold."""
    if coordinator is not None and not participant_id:
        raise ValueError("participant_id is required with a tunnel hold coordinator")
    if synchronization_timeout <= 0:
        raise ValueError("synchronization_timeout must be positive")
    parser = guacamole.GuacamoleInstructionParser(max_buffer_bytes=262144)
    started = time.monotonic()
    synchronization_deadline = started + synchronization_timeout
    ready = False
    synchronized_at: float | None = None
    while True:
        now = time.monotonic()
        boundary = await _hold_boundary_result(
            coordinator=coordinator,
            ready=ready,
            synchronized_at=synchronized_at,
            started=started,
            now=now,
            synchronization_deadline=synchronization_deadline,
            hold_seconds=hold_seconds,
        )
        if boundary is not None:
            return boundary
        receive_timeout = recv_timeout
        if synchronized_at is None:
            receive_timeout = min(recv_timeout, max(synchronization_deadline - now, 0.001))
        try:
            frame = await asyncio.wait_for(socket.recv(), timeout=receive_timeout)
        except TimeoutError:
            continue
        except websockets.ConnectionClosed:
            return await _failed_hold("tunnel_drop", coordinator, ready=ready, synchronized_at=synchronized_at)

        try:
            instructions = parser.feed(frame)
        except guacamole.GuacamoleProtocolError:
            return await _failed_hold("protocol_error", coordinator, ready=ready, synchronized_at=synchronized_at)
        for instruction in instructions:
            if instruction.opcode == "error":
                return await _failed_hold("guacd_error", coordinator, ready=ready, synchronized_at=synchronized_at)
            if instruction.opcode == "ready":
                ready = True
            if instruction.opcode == "sync" and instruction.args:
                await socket.send(guacamole.encode_instruction("sync", instruction.args[0]))
                if ready and synchronized_at is None:
                    synchronized_at = time.monotonic()
                    if coordinator is not None:
                        await coordinator.mark_synchronized(participant_id or "")


class GuacamoleGateExecutor:
    """One real login/range/bootstrap/tunnel lifecycle per participant actor."""

    def __init__(
        self,
        base_url: str,
        *,
        target_role: str = "attacker",
        bootstrap_timeout: float = 90.0,
        connect_timeout: float = 60.0,
        hold_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.target_role = target_role
        self.bootstrap_timeout = bootstrap_timeout
        self.connect_timeout = connect_timeout
        self.hold_seconds = hold_seconds
        self._authenticator = None
        self._coordinator: TunnelHoldCoordinator | None = None
        self._active_clients: dict[str, object] = {}

    async def setup(self, actors: list[Actor], authenticator) -> None:
        """Store the login boundary; each ramped participant performs it in ``__call__``."""
        identities = [actor.email.strip().casefold() for actor in actors]
        if any(not identity for identity in identities) or len(set(identities)) != len(identities):
            raise ValueError("strict Guacamole gate requires distinct participant identities")
        self._authenticator = authenticator
        self._coordinator = TunnelHoldCoordinator(len(actors), self.hold_seconds)

    async def __call__(self, actor: Actor) -> RouteResult:
        started = time.monotonic()
        if self._authenticator is None:
            return await self._fail(started, "authentication_error")
        if self._coordinator is not None and self._coordinator.failure is not None:
            return _failure(started, "peer_failed")
        try:
            client = await self._authenticator(self.base_url, actor)
        except Exception:
            return await self._fail(started, "authentication_error")
        self._active_clients[actor.label] = client
        try:
            try:
                response = await client.get(targets.RANGE_PATH, headers={"Accept": "application/json"})
                if response.status_code >= 400:
                    raise targets.TargetError("range projection was refused")
                target = targets.select_target(_safe_json(response), role=self.target_role)
            except Exception:
                return await self._fail(started, "target_discovery_error")
            status_url = await self._start_bootstrap(client, target)
            delivered_url = await self._await_delivery(client, status_url)
            session_target = guacamole.parse_session_url(delivered_url, base_origin=self.base_url)
            pre_tunnel_seconds = time.monotonic() - started
            async with websockets.connect(
                guacamole.tunnel_ws_url(session_target),
                additional_headers=[("Origin", self.base_url)],
                subprotocols=["guacamole"],
                open_timeout=self.connect_timeout,
                close_timeout=5,
            ) as tunnel:
                hold = await consume_tunnel_until_hold(
                    tunnel,
                    hold_seconds=self.hold_seconds,
                    synchronization_timeout=self.connect_timeout,
                    coordinator=self._coordinator,
                    participant_id=actor.label,
                )
        except _GateFailure as exc:
            return await self._fail(started, exc.category)
        except Exception:
            return await self._fail(started, "tunnel_error")
        finally:
            self._active_clients.pop(actor.label, None)
            with contextlib.suppress(Exception):
                await client.aclose()

        synchronized_after = hold.synchronized_after_seconds
        latency_ms = (pre_tunnel_seconds + (synchronized_after or 0.0)) * 1000.0
        return RouteResult(
            route_class="guacamole:session-hold",
            kind="ws",
            ok=hold.ready and hold.display_synchronized and hold.error_category is None,
            status_code=None,
            latency_ms=latency_ms,
            error_category=hold.error_category,
            ws_opened=True,
            ws_dropped=hold.error_category == "tunnel_drop",
            display_synchronized=hold.display_synchronized,
            held_seconds=hold.held_seconds,
        )

    async def _fail(self, started: float, category: str) -> RouteResult:
        if self._coordinator is not None:
            await self._coordinator.fail(category)
        return _failure(started, category)

    async def _start_bootstrap(self, client, target: targets.RangeTarget) -> str:
        response = await client.post(
            guacamole.bootstrap_path(Protocol.RDP),
            json={"instance_uuid": target.instance_uuid},
            headers=await _csrf_headers(client, self.base_url),
        )
        payload = _safe_json(response)
        status_url = str(payload.get("status_url") or "")
        if response.status_code != 202 or not status_url:
            raise _GateFailure("bootstrap_refused")
        return status_url

    async def _await_delivery(self, client, status_url: str) -> str:
        deadline = time.monotonic() + self.bootstrap_timeout
        while time.monotonic() < deadline:
            response = await client.get(status_url, headers={"Accept": "application/json"})
            payload = _safe_json(response)
            poll = guacamole.classify_poll(response.status_code, payload)
            if poll.delivered:
                return str(payload.get("url") or "")
            if not poll.pending:
                raise _GateFailure("bootstrap_failed")
            await asyncio.sleep(1.0)
        raise _GateFailure("bootstrap_timeout")

    async def aclose(self) -> None:
        for client in tuple(self._active_clients.values()):
            with contextlib.suppress(Exception):
                await client.aclose()
        self._active_clients.clear()


async def run_guacamole_gate(config, actors: list[Actor], executor: GuacamoleGateExecutor) -> Aggregator:
    """Start one participant lifecycle per actor and hold all tunnels concurrently."""
    if len(actors) != config.concurrency:
        raise ValueError("strict Guacamole gate requires exactly one distinct actor per concurrent participant")
    delays = ramp_delays(config.concurrency, config.ramp_seconds)
    aggregator = Aggregator()

    async def participant(index: int) -> None:
        if delays[index]:
            await asyncio.sleep(delays[index])
        aggregator.add(await executor(actors[index]))

    await asyncio.gather(*(participant(index) for index in range(config.concurrency)))
    return aggregator


class _GateFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _failure(started: float, category: str) -> RouteResult:
    return RouteResult(
        route_class="guacamole:session-hold",
        kind="ws",
        ok=False,
        status_code=None,
        latency_ms=(time.monotonic() - started) * 1000.0,
        error_category=category,
    )


async def _csrf_headers(client, base_url: str) -> dict[str, str]:
    if not client.cookies.get("csrftoken"):
        with contextlib.suppress(Exception):
            await client.get("/dashboard/", headers={"Accept": "text/html"})
    headers = {"Referer": f"{base_url}/"}
    token = client.cookies.get("csrftoken")
    if token:
        headers["X-CSRFToken"] = token
    return headers


def _safe_json(response) -> dict[str, object]:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
