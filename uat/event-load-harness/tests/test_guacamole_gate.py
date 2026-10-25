"""Real Guacamole public-path sustained-hold primitives (#1816)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import event_load_harness.guacamole_gate as gate_module
from event_load_harness.auth import Actor
from event_load_harness.guacamole_gate import (
    GuacamoleGateExecutor,
    TunnelHoldCoordinator,
    TunnelHoldResult,
    consume_tunnel_until_hold,
)


class _Socket:
    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []

    async def recv(self) -> str:
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(0)
        return "4.sync,3.124;"

    async def send(self, frame: str) -> None:
        self.sent.append(frame)


class _DelayedSocket(_Socket):
    def __init__(self, frames: list[str], *, initial_delay: float) -> None:
        super().__init__(frames)
        self.initial_delay = initial_delay

    async def recv(self) -> str:
        if self.initial_delay:
            delay, self.initial_delay = self.initial_delay, 0.0
            await asyncio.sleep(delay)
        return await super().recv()


class _NeverSyncSocket(_Socket):
    async def recv(self) -> str:
        await asyncio.sleep(0)
        return "3.nop;"


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {}

    def json(self) -> dict:
        return self.payload


class _Client:
    def __init__(self, *, gets: list[_Response], post: _Response | None = None) -> None:
        self.gets = list(gets)
        self.post_response = post or _Response(500)
        self.cookies = {"csrftoken": "csrf-token"}
        self.posts: list[tuple[str, dict]] = []
        self.closed = False

    async def get(self, _path: str, **_kwargs) -> _Response:
        return self.gets.pop(0)

    async def post(self, path: str, **kwargs) -> _Response:
        self.posts.append((path, kwargs))
        return self.post_response

    async def aclose(self) -> None:
        self.closed = True


class _TunnelContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


def _actor() -> Actor:
    return Actor(label="actor-0001", email="participant@example.invalid")


async def _setup_executor(client: _Client) -> tuple[GuacamoleGateExecutor, Actor]:
    actor = _actor()

    async def authenticate(_base_url, _actor):
        return client

    executor = GuacamoleGateExecutor(
        "https://dev.example.invalid",
        bootstrap_timeout=0.01,
        connect_timeout=0.01,
        hold_seconds=0.01,
    )
    await executor.setup([actor], authenticate)
    return executor, actor


async def test_hold_requires_ready_and_display_sync_then_acks_every_sync():
    socket = _Socket(["5.ready,3.cid;", "4.sync,3.123;"])

    result = await consume_tunnel_until_hold(socket, hold_seconds=0.01, recv_timeout=0.01)

    assert result.ready is True
    assert result.display_synchronized is True
    assert result.held_seconds >= 0.01
    assert "4.sync,3.123;" in socket.sent


async def test_hold_fails_when_tunnel_errors_before_display_sync():
    socket = _Socket(["5.error,6.failed,3.500;"])

    result = await consume_tunnel_until_hold(socket, hold_seconds=0.01, recv_timeout=0.01)

    assert result.ready is False
    assert result.display_synchronized is False
    assert result.error_category == "guacd_error"


async def test_hold_fails_closed_when_an_open_tunnel_never_synchronizes():
    coordinator = TunnelHoldCoordinator(participants=1, hold_seconds=0.01)

    result = await consume_tunnel_until_hold(
        _NeverSyncSocket([]),
        hold_seconds=0.01,
        recv_timeout=0.005,
        synchronization_timeout=0.02,
        coordinator=coordinator,
        participant_id="actor-0001",
    )

    assert result.ready is False
    assert result.display_synchronized is False
    assert result.error_category == "synchronization_timeout"
    assert coordinator.failure == "synchronization_timeout"


async def test_all_tunnels_hold_for_common_duration_after_last_display_sync():
    coordinator = TunnelHoldCoordinator(participants=2, hold_seconds=0.02)
    first = _Socket(["5.ready,3.one;", "4.sync,1.1;"])
    second = _DelayedSocket(["5.ready,3.two;", "4.sync,1.2;"], initial_delay=0.03)

    first_result, second_result = await asyncio.gather(
        consume_tunnel_until_hold(
            first,
            hold_seconds=0.02,
            recv_timeout=0.05,
            coordinator=coordinator,
            participant_id="actor-0001",
        ),
        consume_tunnel_until_hold(
            second,
            hold_seconds=0.02,
            recv_timeout=0.05,
            coordinator=coordinator,
            participant_id="actor-0002",
        ),
    )

    assert first_result.display_synchronized is True
    assert second_result.display_synchronized is True
    assert first_result.held_seconds >= 0.04
    assert second_result.held_seconds >= 0.018


async def test_gate_defers_real_login_until_each_ramped_participant_journey():
    calls = []

    async def authenticator(_base_url, actor):
        calls.append(actor.label)
        raise RuntimeError("test login failure")

    actor = Actor(label="actor-0001", email="participant@example.invalid")
    executor = GuacamoleGateExecutor("https://dev.example.invalid", hold_seconds=0.01)

    await executor.setup([actor], authenticator)
    assert calls == []

    result = await executor(actor)
    assert calls == ["actor-0001"]
    assert result.ok is False
    assert result.error_category == "authentication_error"


async def test_gate_rejects_target_discovery_refusal():
    client = _Client(gets=[_Response(503)])
    executor, actor = await _setup_executor(client)

    result = await executor(actor)

    assert result.ok is False
    assert result.error_category == "target_discovery_error"
    assert client.closed is True


async def test_gate_rejects_bootstrap_without_accepted_status(monkeypatch):
    client = _Client(gets=[_Response(200, {"targets": []})], post=_Response(200, {}))
    executor, actor = await _setup_executor(client)
    monkeypatch.setattr(
        gate_module.targets,
        "select_target",
        lambda _payload, role: SimpleNamespace(instance_uuid="instance-1", role=role),
    )

    result = await executor(actor)

    assert result.ok is False
    assert result.error_category == "bootstrap_refused"


async def test_gate_rejects_failed_delivery_poll(monkeypatch):
    client = _Client(
        gets=[_Response(200, {"targets": []}), _Response(200, {"status": "failed"})],
        post=_Response(202, {"status_url": "/api/bootstrap/status/1"}),
    )
    executor, actor = await _setup_executor(client)
    monkeypatch.setattr(
        gate_module.targets,
        "select_target",
        lambda _payload, role: SimpleNamespace(instance_uuid="instance-1", role=role),
    )

    result = await executor(actor)

    assert result.ok is False
    assert result.error_category == "bootstrap_failed"


async def test_gate_rejects_delivery_timeout(monkeypatch):
    client = _Client(
        gets=[_Response(200, {"targets": []})],
        post=_Response(202, {"status_url": "/api/bootstrap/status/1"}),
    )
    executor, actor = await _setup_executor(client)
    executor.bootstrap_timeout = 0
    monkeypatch.setattr(
        gate_module.targets,
        "select_target",
        lambda _payload, role: SimpleNamespace(instance_uuid="instance-1", role=role),
    )

    result = await executor(actor)

    assert result.ok is False
    assert result.error_category == "bootstrap_timeout"


async def test_gate_full_success_path_requires_delivered_url_and_synchronized_hold(monkeypatch):
    client = _Client(
        gets=[
            _Response(200, {"targets": []}),
            _Response(200, {"status": "succeeded", "url": "/guacamole/#/client/id?token=secret"}),
        ],
        post=_Response(202, {"status_url": "/api/bootstrap/status/1"}),
    )
    executor, actor = await _setup_executor(client)
    monkeypatch.setattr(
        gate_module.targets,
        "select_target",
        lambda _payload, role: SimpleNamespace(instance_uuid="instance-1", role=role),
    )
    monkeypatch.setattr(gate_module.guacamole, "parse_session_url", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(gate_module.guacamole, "tunnel_ws_url", lambda _target: "wss://dev.example.invalid/tunnel")
    connect_calls = []

    def connect(*args, **kwargs):
        connect_calls.append((args, kwargs))
        return _TunnelContext()

    async def successful_hold(_socket, **_kwargs):
        return TunnelHoldResult(
            ready=True,
            display_synchronized=True,
            held_seconds=0.02,
            synchronized_after_seconds=0.001,
        )

    monkeypatch.setattr(gate_module.websockets, "connect", connect)
    monkeypatch.setattr(gate_module, "consume_tunnel_until_hold", successful_hold)

    result = await executor(actor)

    assert result.ok is True
    assert result.display_synchronized is True
    assert result.error_category is None
    assert client.posts == [
        (
            "/api/v1/mission-control/guacamole/rdp-url/",
            {
                "json": {"instance_uuid": "instance-1"},
                "headers": {"Referer": "https://dev.example.invalid/", "X-CSRFToken": "csrf-token"},
            },
        )
    ]
    assert connect_calls[0][0] == ("wss://dev.example.invalid/tunnel",)
    assert connect_calls[0][1]["subprotocols"] == ["guacamole"]
