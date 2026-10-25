"""Black-box listener tests with only its remote control/provider ports replaced."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from model_broker.server import BrokerApplication
from shared.model_access import ContractError
from shared.model_access.credentials import ModelAccessAuthorization
from shared.model_access.provider import ProviderUsage, VerifiedUsage
from tests.engine.services.test_model_request_accounting import _bound, _limits, seal_v3_catalog

pytestmark = pytest.mark.asyncio
_TOKEN = str(uuid4()) + "." + "a" * 43
_HEADERS = {"x-api-key": _TOKEN, "anthropic-version": "2023-06-01"}
_BODY = {
    "model": "coding-main",
    "messages": [{"role": "user", "content": "private synthetic prompt"}],
    "max_tokens": 10,
}


class ControlPort:
    def __init__(self, *, deny=""):
        self.calls = []
        self.deny = deny
        self.authority = ModelAccessAuthorization(
            allocation_id=uuid4(),
            operation_id=uuid4(),
            grant_epoch=1,
            aliases={"coding-main": seal_v3_catalog(uuid4()).shards[0]},
            limits=_limits(),
            hard_expires_at="2027-01-01T00:00:00Z",
        )

    async def call(self, route, payload):
        action = payload.get("action", route)
        self.calls.append((action, payload))
        if action == self.deny:
            raise ContractError("control.unavailable")
        if route == "authenticate":
            return self.authority.model_dump(mode="json")
        if route == "reserve":
            return {"request_uuid": payload["request_uuid"]}
        if action == "dispatch":
            return {"dispatch_token": "lease-token"}
        return {}


class ProviderPort:
    def __init__(self, *, stall=False):
        self.invocations = 0
        self.closed = False
        self.stall = stall

    def build(self, shard, limits):
        return self

    def capabilities(self):
        return SimpleNamespace(token_counting=False)

    def message_billing_bound(self, message, *, count_only, input_tokens=None):
        return _bound()

    @asynccontextmanager
    async def invoke(self, message, *, count_only, before_transport, precounted=None):
        self.invocations += 1

        async def chunks():
            if self.stall:
                yield b'event: message_start\ndata: {"type":"message_start"}\n\n'
                await asyncio.Event().wait()
            yield b'{"content":[{"type":"text","text":"synthetic answer"}]}'

        response = SimpleNamespace(
            chunks=chunks(),
            content_type="text/event-stream" if self.stall else "application/json",
            usage=ProviderUsage(items=(VerifiedUsage(component="input_tokens", units=5, provider_verified=True),)),
        )
        try:
            yield response
        finally:
            self.closed = True


def app(control, provider):
    return BrokerApplication(control=control, providers=provider, fingerprint_key=b"k" * 32, key_version="v1")


async def test_only_reserved_and_fenced_request_reaches_provider():
    control, provider = ControlPort(), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)
    assert result.status_code == 200
    assert result.json()["content"][0]["text"] == "synthetic answer"
    assert [action for action, _ in control.calls] == ["authenticate", "reserve", "dispatch", "check", "settle"]
    assert "private synthetic prompt" not in json.dumps(control.calls)
    assert provider.invocations == 1 and provider.closed


@pytest.mark.parametrize("deny", ["authenticate", "reserve", "dispatch", "check"])
async def test_control_failure_prevents_provider_effect(deny):
    control, provider = ControlPort(deny=deny), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)
    assert result.status_code != 200
    assert provider.invocations == 0


async def test_continuation_failure_closes_upstream_and_retains_liability():
    control, provider = ControlPort(deny="continue"), ProviderPort(stall=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await asyncio.wait_for(
            client.post("/v1/messages", headers=_HEADERS, json={**_BODY, "stream": True}), timeout=5
        )
    assert b"broker.interrupted" in result.content
    assert provider.closed
    assert provider.invocations == 1
    assert control.calls[-1][0] == "unknown"
    assert not any(action == "settle" for action, _ in control.calls)


async def test_disconnect_cancels_transport_without_refund_or_retry():
    control, provider = ControlPort(), ProviderPort(stall=True)
    queue = asyncio.Queue()
    await queue.put({"type": "http.request", "body": json.dumps({**_BODY, "stream": True}).encode()})
    sent = []

    async def send(event):
        sent.append(event)
        if event["type"] == "http.response.body" and event.get("more_body"):
            await queue.put({"type": "http.disconnect"})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "query_string": b"",
        "client": ("10.80.2.17", 1234),
        "headers": [
            (key.encode(), value.encode()) for key, value in {**_HEADERS, "content-type": "application/json"}.items()
        ],
    }
    await asyncio.wait_for(app(control, provider)(scope, queue.get, send), timeout=2)
    assert provider.closed and provider.invocations == 1
    assert control.calls[-1][0] == "unknown"


async def test_private_control_is_not_a_participant_route():
    control, provider = ControlPort(), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/control/v1/enroll", headers=_HEADERS, json={})
    assert result.status_code != 200
    assert control.calls == []


async def test_source_projection_is_private_and_required_before_reservation():
    control, provider = ControlPort(deny="source"), ProviderPort()
    shard = control.authority.aliases["coding-main"]
    control.authority.aliases["coding-main"] = shard.model_copy(
        update={
            "credential_ref": shard.credential_ref.model_copy(
                update={"reference": "source:00000000-0000-0000-0000-000000000001:1"}
            )
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)
    assert result.status_code != 200
    assert [action for action, _ in control.calls] == ["authenticate", "source"]
    assert control.calls[-1][1] == {"token": _TOKEN, "transport_peer": "127.0.0.1", "logical_alias": "coding-main"}
    assert provider.invocations == 0
