"""Full broker/control/accounting flow over real local HTTP and verified TLS."""

import asyncio
import json
import logging
import socket
import ssl
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async

from engine.model_access_control.server import ControlApplication
from engine.models import ModelRequestReservation, SubnetAllocation
from engine.services._model_allocation_lifecycle import revoke_model_generation
from model_broker.control import ControlClient
from model_broker.providers import ProviderRegistry
from model_broker.server import BrokerApplication
from shared.model_access.provider_runtime import ProviderInventory, ProviderTarget
from shared.models import AuditLog

from .model_broker_http_support import (
    ANSWER,
    ERROR,
    PROMPT,
    PROOF,
    ProviderCredentials,
    ProviderServer,
    ProviderTransport,
    enable_count,
    listener,
    private_host,
    tls_identity,
)
from .test_model_credentials import enrolled_allocation, issue

__all__ = ["enrolled_allocation"]
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest_asyncio.fixture
async def stack(enrolled_allocation, tmp_path):
    host = private_host()
    cert, key, assertion, verifier = tls_identity(tmp_path, host)
    await sync_to_async(enable_count)(enrolled_allocation)
    await sync_to_async(lambda: SubnetAllocation.objects.update(cidr=f"{host}/32"))()
    enrollment = await sync_to_async(issue)(enrolled_allocation)
    upstream = ProviderServer()
    control_app = ControlApplication(verify_identity=verifier, ready=lambda: True)
    shard = enrolled_allocation.snapshot["shards"]["coding-main"]
    target = ProviderTarget(
        shard_id=shard["shard_id"],
        provider="vertex-v1",
        region=shard["region"],
        count_region="eu",
        model=shard["provider_model"],
        credential_reference=shard["credential_ref"]["reference"],
        project="models-example",
        principal="model-test@models-example.iam.gserviceaccount.com",
        context_window_tokens=200_000,
    )
    async with (
        listener(upstream, host, cert, key) as (provider_url, _),
        listener(control_app, host, cert, key) as (control_url, control_server),
    ):
        control = ControlClient(url=control_url, ca_file=str(cert), identity=assertion)
        providers = ProviderRegistry(
            inventory=ProviderInventory(contract_version="model-broker-providers/v1", targets=[target]),
            credentials=ProviderCredentials(),
            client=httpx.AsyncClient(
                transport=ProviderTransport(provider_url, cert), trust_env=False, follow_redirects=False
            ),
        )
        broker = BrokerApplication(control=control, providers=providers, fingerprint_key=b"f" * 32, key_version="v1")
        try:
            async with (
                listener(broker, host, cert, key, broker=True) as (broker_url, broker_server),
                httpx.AsyncClient(
                    base_url=broker_url,
                    trust_env=False,
                    transport=httpx.AsyncHTTPTransport(
                        verify=ssl.create_default_context(cafile=str(cert)), local_address=host
                    ),
                ) as client,
            ):
                response = await client.post(
                    "/v1/access/exchange", json={"token": enrollment.enrollment_token.get_secret_value()}
                )
                assert response.status_code == 200, response.text
                yield SimpleNamespace(
                    client=client,
                    upstream=upstream,
                    broker=broker,
                    broker_server=broker_server,
                    control_server=control_server,
                    allocation=enrolled_allocation,
                    token=response.json()["access_token"],
                    refresh=response.json()["refresh_token"],
                    enrollment=enrollment.enrollment_token.get_secret_value(),
                    hard_expiry=response.json()["hard_expires_at"],
                    cert=cert,
                )
        finally:
            await control.close()
            await providers.close()


def headers(stack):
    return {"x-api-key": stack.token, "anthropic-version": "2023-06-01"}


def message(*, stream=False):
    return {
        "model": "coding-main",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 10,
        "stream": stream,
    }


@pytest.mark.parametrize("stream", [False, True])
async def test_full_tls_message_settles_and_keeps_content_out_of_accounting(stack, stream, caplog):
    stack.upstream.mode = "stream" if stream else "json"
    response = await stack.client.post("/v1/messages", headers=headers(stack), json=message(stream=stream))
    assert response.status_code == 200, response.text
    assert ANSWER in response.text
    assert len(stack.upstream.requests) == 2
    assert "count-tokens" in stack.upstream.requests[0][0]
    assert stack.upstream.requests[-1][2][b"authorization"] == PROOF.encode()
    assert b"x-api-key" not in stack.upstream.requests[-1][2]
    reservation = await sync_to_async(ModelRequestReservation.objects.get)()
    assert reservation.settlement_state == "settled"
    audit = await sync_to_async(lambda: json.dumps(list(AuditLog.objects.values()), default=str))()
    persisted = json.dumps(reservation.__dict__, default=str)
    for marker in (PROMPT, ANSWER, PROOF, stack.token, stack.refresh):
        assert marker not in audit + persisted + caplog.text


@pytest.mark.parametrize("fault", ["auth-conflict", "headers", "beta", "version", "depth", "route", "access-size"])
async def test_invalid_live_http_request_has_no_provider_or_accounting_effect(stack, fault, caplog):
    request_headers = headers(stack)
    payload = message()
    path = "/v1/messages"
    if fault == "auth-conflict":
        request_headers["authorization"] = "Bearer " + stack.token
    elif fault == "headers":
        request_headers.update({f"x-extra-{index}": "value" for index in range(65)})
    elif fault == "beta":
        request_headers["anthropic-beta"] = "unapproved"
    elif fault == "version":
        request_headers["anthropic-version"] = "unknown"
    elif fault == "depth":
        nested = PROMPT
        for _ in range(40):
            nested = {"nested": nested}
        payload["messages"][0]["content"] = nested
    elif fault == "route":
        path = "/control/v1/enroll"
    else:
        path, request_headers, payload = "/v1/access/exchange", {}, {"token": PROMPT * 200}
    response = await stack.client.post(path, headers=request_headers, json=payload)
    assert response.status_code != 200
    assert stack.upstream.requests == []
    assert not await sync_to_async(ModelRequestReservation.objects.exists)()
    assert PROMPT not in response.text + caplog.text
    assert stack.token not in response.text + caplog.text


async def test_exchange_refresh_rotation_and_completed_retry_never_replay_plaintext(stack):
    replay = await stack.client.post("/v1/access/exchange", json={"token": stack.enrollment})
    assert replay.status_code == 401
    pair = await stack.client.post("/v1/access/refresh", json={"token": stack.refresh})
    assert pair.status_code == 200, pair.text
    assert pair.json()["hard_expires_at"] == stack.hard_expiry
    assert (await stack.client.get("/v1/models", headers=headers(stack))).status_code == 401
    assert (await stack.client.post("/v1/access/refresh", json={"token": stack.refresh})).status_code == 401
    stack.token = pair.json()["access_token"]
    models = await stack.client.get("/v1/models", headers=headers(stack))
    assert [model["id"] for model in models.json()["data"]] == ["coding-main"]
    request_headers = {**headers(stack), "idempotency-key": "synthetic-retry-2122"}
    response = await stack.client.post("/v1/messages", headers=request_headers, json=message())
    assert response.status_code == 200
    repeated = await stack.client.post("/v1/messages", headers=request_headers, json=message())
    assert repeated.status_code == 409
    assert repeated.json()["type"] == "completed"
    assert ANSWER not in repeated.text
    assert len(stack.upstream.requests) == 2
    assert await sync_to_async(ModelRequestReservation.objects.count)() == 1


async def test_live_count_uses_exact_route_and_zero_price_with_rate_accounting(stack):
    payload = message()
    del payload["max_tokens"], payload["stream"]
    response = await stack.client.post("/v1/messages/count_tokens", headers=headers(stack), json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == {"input_tokens": 5}
    assert len(stack.upstream.requests) == 1
    assert "count-tokens" in stack.upstream.requests[0][0]
    reservation = await sync_to_async(ModelRequestReservation.objects.get)()
    assert reservation.settlement_state == "settled"
    assert reservation.canonical_request_cost == 0
    assert await sync_to_async(lambda: reservation.postings.filter(account__dimension="rate").exists())()


@pytest.mark.postgres
async def test_refresh_race_over_live_http_has_one_winner(stack):
    results = await asyncio.gather(
        *(stack.client.post("/v1/access/refresh", json={"token": stack.refresh}) for _ in range(2))
    )
    assert sorted(response.status_code for response in results) == [200, 401]
    winner = next(response.json() for response in results if response.status_code == 200)
    assert winner["hard_expires_at"] == stack.hard_expiry
    response = await stack.client.get("/v1/models", headers={"x-api-key": winner["access_token"]})
    assert response.status_code == 200


@pytest.mark.parametrize("mode", ["error", "redirect"])
async def test_provider_failure_never_retries_redirects_or_leaks_diagnostics(stack, mode, caplog):
    caplog.set_level(logging.DEBUG)
    stack.upstream.mode = mode
    response = await stack.client.post("/v1/messages", headers=headers(stack), json=message())
    assert response.status_code != 200
    assert len(stack.upstream.requests) == 2
    assert ERROR not in response.text + caplog.text
    assert PROMPT not in caplog.text
    assert PROOF not in caplog.text
    reservation = await sync_to_async(ModelRequestReservation.objects.get)()
    assert reservation.state == "unknown"


async def test_slow_socket_consumer_cannot_delay_upstream_revocation(stack):
    stack.upstream.mode = "flood"
    origin = stack.client.base_url
    _, writer = await asyncio.open_connection(
        origin.host, origin.port, ssl=ssl.create_default_context(cafile=str(stack.cert)), limit=1024
    )
    writer.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    raw = json.dumps(message(stream=True)).encode()
    request = (
        f"POST /v1/messages HTTP/1.1\r\nHost: {origin.host}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
        f"x-api-key: {stack.token}\r\nanthropic-version: 2023-06-01\r\n\r\n"
    ).encode() + raw
    try:
        writer.write(request)
        await writer.drain()
        await asyncio.wait_for(stack.upstream.started.wait(), 3)
        await asyncio.sleep(0.15)
        assert not stack.upstream.closed.is_set()
        started = asyncio.get_running_loop().time()
        await sync_to_async(revoke_model_generation)(stack.allocation.range_id)
        await asyncio.wait_for(stack.upstream.closed.wait(), 9)
        assert asyncio.get_running_loop().time() - started < 10
        assert stack.upstream.chunks_sent < 128
    finally:
        writer.close()
        # Abort the intentionally unread TLS stream; graceful close waits for its peer.
        writer.transport.abort()


# The broker settles the reservation from its own thread while this test polls it.
# SQLite locks the table for that write, so the read fails intermittently with
# "database table is locked"; the concurrency this asserts needs PostgreSQL.
@pytest.mark.postgres
@pytest.mark.parametrize("fence", ["revoke", "control_loss", "disconnect", "drain", "deadline"])
async def test_live_stream_fences_within_ten_seconds_and_keeps_liability(stack, fence):
    if fence == "deadline":
        stack.allocation.snapshot["effective_policy"]["effective_profile"]["limits"]["max_request_seconds"] = 2
        await sync_to_async(stack.allocation.save)(update_fields=["snapshot"])
    stack.upstream.mode = "stall"
    async with stack.client.stream(
        "POST", "/v1/messages", headers=headers(stack), json=message(stream=True)
    ) as response:
        assert response.status_code == 200
        lines = response.aiter_lines()
        # Tiny SSE frames must be delivered without waiting for a 16 KiB buffer.
        first = await asyncio.wait_for(anext(lines), 1)
        assert first == "event: message_start"
        started = asyncio.get_running_loop().time()
        if fence == "revoke":
            await sync_to_async(revoke_model_generation)(stack.allocation.range_id)
        elif fence == "control_loss":
            stack.control_server.should_exit = True
        elif fence == "drain":
            # Invoking Uvicorn's signal handler while serve() owns its signal
            # capture replays SIGTERM when the server exits, killing xdist's
            # worker instead of completing this in-process transport test.
            stack.broker.begin_drain()
            stack.broker_server.should_exit = True
        elif fence == "disconnect":
            await response.aclose()
        await asyncio.wait_for(stack.upstream.closed.wait(), 9)
        assert asyncio.get_running_loop().time() - started < 10
        if fence != "disconnect":
            async with asyncio.timeout(2):
                remaining = [line async for line in lines]
            assert "event: error" in remaining
            assert "broker.interrupted" in "".join(remaining)
    async with asyncio.timeout(3):
        while True:
            reservation = await sync_to_async(ModelRequestReservation.objects.get)()
            if reservation.state == "unknown" or fence == "control_loss":
                break
            await asyncio.sleep(0.02)
    assert reservation.settlement_state != "settled"
    assert reservation.canonical_request_cost > 0
    assert len(stack.upstream.requests) == 2
