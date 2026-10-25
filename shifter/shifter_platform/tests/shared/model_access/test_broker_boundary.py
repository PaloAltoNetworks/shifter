"""Participant boundary regressions for bounded admission and transport fencing."""

import asyncio
import json
from contextlib import suppress

import httpx
import pytest

from shared.model_access import ContractError
from tests.shared.model_access.test_broker_listener import (
    _BODY,
    _HEADERS,
    ControlPort,
    ProviderPort,
    app,
)

pytestmark = pytest.mark.asyncio


async def test_models_exposes_only_current_grant_aliases():
    control, provider = ControlPort(), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        response = await client.get("/v1/models", headers=_HEADERS)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]] == ["coding-main"]
        assert response.json()["has_more"] is False
        shard = control.authority.aliases["coding-main"]
        assert shard.provider_model not in response.text
        assert shard.credential_ref.reference not in response.text
        control.deny = "authenticate"
        denied = await client.get("/v1/models", headers=_HEADERS)
        assert denied.status_code != 200
        assert "coding-main" not in denied.text
    assert provider.invocations == 0


@pytest.mark.parametrize(
    "extra",
    [
        [("authorization", "")],
        [(f"x-extra-{index}", "x") for index in range(65)],
        [(f"x-extra-{index}", "x" * 10_000) for index in range(4)],
        [("x" * 257, "value")],
        [("x-extra", "line\r\ninjected")],
    ],
)
async def test_ambiguous_or_oversized_headers_never_reach_control(extra):
    control, provider = ControlPort(), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        response = await client.post("/v1/messages", headers=[*_HEADERS.items(), *extra], json=_BODY)
    assert response.status_code != 200
    assert control.calls == []
    assert provider.invocations == 0


async def test_exchange_rejects_a_second_credential_source():
    control, provider = ControlPort(), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        response = await client.post("/v1/access/exchange", headers=_HEADERS, json={"token": _HEADERS["x-api-key"]})
    assert response.status_code != 200
    assert control.calls == []


def scope():
    return {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "query_string": b"",
        "client": ("10.80.2.17", 1234),
        "headers": [
            (key.encode(), value.encode()) for key, value in {**_HEADERS, "content-type": "application/json"}.items()
        ],
    }


async def test_revocation_closes_provider_before_attempting_a_stalled_error_write():
    denied, writing = asyncio.Event(), asyncio.Event()

    class RevokingControl(ControlPort):
        async def call(self, route, payload):
            if payload.get("action") == "continue":
                denied.set()
                raise ContractError("request.revoked")
            return await super().call(route, payload)

    control, provider = RevokingControl(), ProviderPort(stall=True)
    queue = asyncio.Queue()
    await queue.put({"type": "http.request", "body": json.dumps({**_BODY, "stream": True}).encode()})

    async def send(event):
        if event["type"] == "http.response.body":
            writing.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(app(control, provider)(scope(), queue.get, send))
    try:
        await asyncio.wait_for(writing.wait(), 1)
        await asyncio.wait_for(denied.wait(), 3)
        await asyncio.sleep(0.05)
        assert provider.closed, "upstream fence must not wait for a downstream error write"
        await asyncio.wait_for(asyncio.shield(task), 2)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert control.calls[-1][0] == "unknown"
    assert provider.invocations == 1


async def test_request_deadline_includes_reservation_and_dispatch():
    class SlowControl(ControlPort):
        async def call(self, route, payload):
            if route == "reserve":
                await asyncio.sleep(1.2)
            return await super().call(route, payload)

    control, provider = SlowControl(), ProviderPort()
    control.authority = control.authority.model_copy(
        update={"limits": control.authority.limits.model_copy(update={"max_request_seconds": 1})}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        response = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)
    assert response.status_code != 200
    assert provider.invocations == 0


async def test_access_upload_is_bounded_before_reading_the_entire_messages_allowance():
    control, provider = ControlPort(), ProviderPort()
    reads, sent = [], []

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b"x" * 4097, "more_body": len(reads) < 3}

    async def send(event):
        sent.append(event)

    request = {**scope(), "path": "/v1/access/exchange", "headers": [(b"content-type", b"application/json")]}
    await app(control, provider)(request, receive, send)
    assert len(reads) == 1
    assert sent[0]["status"] != 200
    assert control.calls == []


async def test_source_resolution_still_obeys_the_absolute_request_deadline():
    class SlowSource(ControlPort):
        async def call(self, route, payload):
            if route == "source":
                await asyncio.sleep(2)
            return await super().call(route, payload)

    control, provider = SlowSource(), ProviderPort()
    shard = control.authority.aliases["coding-main"]
    control.authority = control.authority.model_copy(
        update={
            "limits": control.authority.limits.model_copy(update={"max_request_seconds": 1}),
            "aliases": {
                "coding-main": shard.model_copy(
                    update={"credential_ref": shard.credential_ref.model_copy(update={"reference": "source:synthetic"})}
                )
            },
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        async with asyncio.timeout(1.5):
            response = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)
    assert response.status_code == 400
    assert provider.invocations == 0


async def test_credential_guessing_is_bounded_before_control_calls():
    control, provider = ControlPort(deny="exchange"), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        responses = [
            await client.post("/v1/access/exchange", json={"token": _HEADERS["x-api-key"]}) for _ in range(121)
        ]
    assert responses[-1].status_code == 429
    assert len(control.calls) <= 120


async def test_readiness_requires_control_authority():
    control, provider = ControlPort(deny="ready"), ProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        assert (await client.get("/health/ready")).status_code == 503
        assert (await client.get("/health/live")).status_code == 200


async def test_expiring_started_json_never_sends_a_second_response_or_sse():
    control, provider = ControlPort(), ProviderPort(stall=True)
    control.authority = control.authority.model_copy(
        update={"limits": control.authority.limits.model_copy(update={"max_request_seconds": 1})}
    )
    queue, sent = asyncio.Queue(), []
    await queue.put({"type": "http.request", "body": json.dumps(_BODY).encode()})

    async def send(event):
        sent.append(event)

    await app(control, provider)(scope(), queue.get, send)
    assert sum(event["type"] == "http.response.start" for event in sent) == 1
    assert b"event: error" not in b"".join(event.get("body", b"") for event in sent)
    assert provider.closed


@pytest.mark.parametrize("stream", [False, True])
async def test_deadline_completes_the_started_response_without_overlapping_timers(stream):
    control, provider = ControlPort(), ProviderPort(stall=True)
    control.authority = control.authority.model_copy(
        update={"limits": control.authority.limits.model_copy(update={"max_request_seconds": 1})}
    )
    queue, sent = asyncio.Queue(), []
    await queue.put({"type": "http.request", "body": json.dumps({**_BODY, "stream": stream}).encode()})

    async def send(event):
        sent.append(event)

    await asyncio.wait_for(app(control, provider)(scope(), queue.get, send), 3)
    assert provider.closed
    assert sum(event["type"] == "http.response.start" for event in sent) == 1
    assert sent[-1]["type"] == "http.response.body"
    assert sent[-1].get("more_body", False) is False
    content = b"".join(event.get("body", b"") for event in sent)
    assert (b"event: error" in content) is stream
    assert control.calls[-1][0] == "unknown"


async def test_drain_fences_active_stream_and_new_admission():
    control, provider = ControlPort(), ProviderPort(stall=True)
    application = app(control, provider)
    queue, started = asyncio.Queue(), asyncio.Event()
    await queue.put({"type": "http.request", "body": json.dumps({**_BODY, "stream": True}).encode()})

    async def send(event):
        if event["type"] == "http.response.body":
            started.set()

    task = asyncio.create_task(application(scope(), queue.get, send))
    try:
        await asyncio.wait_for(started.wait(), 1)
        application.begin_drain()
        await asyncio.wait_for(asyncio.shield(task), 1)
        assert provider.closed
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="https://broker.invalid"
        ) as client:
            assert (await client.get("/v1/models", headers=_HEADERS)).status_code != 200
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
