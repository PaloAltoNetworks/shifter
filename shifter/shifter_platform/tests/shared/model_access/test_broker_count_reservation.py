"""Count-based pre-dispatch reservation: routine small prompts are not denied.

A paid request against a counting provider reserves its input against a
provider-proven token count, not the full physical context window (#2124). The
count itself is an accounted, authority-checked reserve/dispatch/settle cycle;
the paid reservation that follows uses the proven count for its input bound.
Providers without a count endpoint keep the conservative full-context bound.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from model_broker.server import BrokerApplication
from shared.model_access.core_models import BillingComponent
from shared.model_access.credentials import ModelAccessAuthorization
from shared.model_access.provider import (
    BillingAmount,
    BillingBound,
    ProviderCapabilities,
    ProviderUsage,
    VerifiedUsage,
)
from tests.engine.services.test_model_request_accounting import _limits, seal_v3_catalog

pytestmark = pytest.mark.asyncio
_TOKEN = str(uuid4()) + "." + "a" * 43
_HEADERS = {"x-api-key": _TOKEN, "anthropic-version": "2023-06-01"}
_BODY = {
    "model": "coding-main",
    "messages": [{"role": "user", "content": "a routine short prompt"}],
    "max_tokens": 10,
}
_CONTEXT_WINDOW = 200_000
_PROVEN_COUNT = 12


class CountingControlPort:
    """Records the billing bound each reservation carries, keyed by request uuid."""

    def __init__(self, *, count_enabled=True):
        self.calls = []
        self.reserved_bounds = []
        self.committed_bounds = []
        shard = seal_v3_catalog(uuid4()).shards[0]
        if count_enabled:
            shard = shard.model_copy(update={"capabilities": ("messages", "token-count")})
        self.authority = ModelAccessAuthorization(
            allocation_id=uuid4(),
            operation_id=uuid4(),
            grant_epoch=1,
            aliases={"coding-main": shard},
            limits=_limits(),
            hard_expires_at="2027-01-01T00:00:00Z",
        )

    async def call(self, route, payload):
        action = payload.get("action", route)
        self.calls.append((action, payload))
        if route == "authenticate":
            return self.authority.model_dump(mode="json")
        if route == "reserve":
            self.reserved_bounds.append(payload["billing_bound"])
            return {"request_uuid": payload["request_uuid"]}
        if route == "commit":
            self.committed_bounds.append(payload["billing_bound"])
            return {"canonical_request_cost": 0}
        if action == "dispatch":
            return {"dispatch_token": "lease-token", "deadline": "2027-01-01T00:00:00Z"}
        if action == "continue":
            return {"deadline": "2027-01-01T00:00:00Z", "revision": 1}
        return {}


class CountingProviderPort:
    """A counting provider whose count() proves a small input before the paid call."""

    def __init__(self):
        self.counted = 0
        self.invocations = 0
        self.closed = False
        self.precounted = None

    def build(self, shard, limits):
        return self

    def capabilities(self):
        return ProviderCapabilities(
            adapter_id="vertex-v1",
            protocols=("anthropic-messages/2023-06-01",),
            models=("publishers/anthropic/models/claude-sonnet",),
            capabilities=("messages", "token-count"),
            billing_components=(
                BillingComponent.INPUT_TOKENS,
                BillingComponent.OUTPUT_TOKENS,
                BillingComponent.REQUEST,
            ),
            trustworthy_usage_components=(
                BillingComponent.INPUT_TOKENS,
                BillingComponent.OUTPUT_TOKENS,
                BillingComponent.REQUEST,
            ),
            streaming=True,
            token_counting=True,
            cancellation=False,
            completion_horizon_seconds=900,
        )

    def message_billing_bound(self, message, *, count_only, input_tokens=None):
        if count_only:
            return BillingBound(
                amounts=(BillingAmount(component=BillingComponent.REQUEST, units=1, maximum_charge_micro_units=0),)
            )
        return BillingBound(
            amounts=(
                BillingAmount(
                    component=BillingComponent.INPUT_TOKENS,
                    units=input_tokens if input_tokens is not None else _CONTEXT_WINDOW,
                    maximum_charge_micro_units=0,
                ),
                BillingAmount(
                    component=BillingComponent.OUTPUT_TOKENS, units=message.max_tokens, maximum_charge_micro_units=0
                ),
            )
        )

    async def count(self, message, *, before_transport):
        self.counted += 1
        return _PROVEN_COUNT

    @asynccontextmanager
    async def invoke(self, message, *, count_only, before_transport, precounted=None):
        self.invocations += 1
        self.precounted = precounted

        async def chunks():
            yield b'{"content":[{"type":"text","text":"synthetic answer"}]}'

        response = SimpleNamespace(
            chunks=chunks(),
            content_type="application/json",
            usage=ProviderUsage(
                items=(
                    VerifiedUsage(component=BillingComponent.INPUT_TOKENS, units=_PROVEN_COUNT, provider_verified=True),
                    VerifiedUsage(component=BillingComponent.OUTPUT_TOKENS, units=5, provider_verified=True),
                )
            ),
        )
        try:
            yield response
        finally:
            self.closed = True


class FailingCountProviderPort(CountingProviderPort):
    """A counting provider whose free count operation proves no billable effect."""

    async def count(self, message, *, before_transport):
        from model_broker.errors import NoBillableEffect

        self.counted += 1
        raise NoBillableEffect("provider.count_unavailable", count_only=False)


def _app(control, provider):
    return BrokerApplication(control=control, providers=provider, fingerprint_key=b"k" * 32, key_version="v1")


async def test_count_first_count_failure_settles_free_count_without_paid_liability():
    # A count-first attempt whose count fails before commit must terminalize as the
    # free count (request component settled at zero), never a paid unknown liability.
    control, provider = CountingControlPort(), FailingCountProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)

    assert result.status_code != 200  # no paid invocation followed the failed count
    actions = [action for action, _ in control.calls]
    assert "commit" not in actions and "unknown" not in actions
    assert provider.invocations == 0  # the paid transfer never started
    settle = next(payload for action, payload in control.calls if action == "settle")
    assert [item["component"] for item in settle["usage"]["items"]] == ["request"]
    assert settle["usage"]["items"][0]["units"] == 0


async def test_paid_request_reserves_against_proven_count_not_full_context():
    control, provider = CountingControlPort(), CountingProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)

    assert result.status_code == 200
    assert result.json()["content"][0]["text"] == "synthetic answer"
    # One reservation admitted with the free count bound, dispatched, counted, then
    # its proven input/output spend committed before the paid transfer settles.
    assert [action for action, _ in control.calls] == [
        "authenticate",
        "reserve",
        "dispatch",
        "check",
        "commit",
        "settle",
    ]
    assert provider.counted == 1 and provider.invocations == 1 and provider.closed
    assert provider.precounted == _PROVEN_COUNT
    # The reservation is admitted on the free count bound; commit narrows input to the proven count.
    assert [(a["component"], a["units"]) for a in control.reserved_bounds[0]["amounts"]] == [("request", 1)]
    paid_input = next(a for a in control.committed_bounds[0]["amounts"] if a["component"] == "input_tokens")
    assert paid_input["units"] == _PROVEN_COUNT  # not the 200k physical context window
    # Reserve and commit act on the single participant request uuid.
    reserve_uuid = next(p["request_uuid"] for a, p in control.calls if a == "reserve")
    commit_uuid = next(p["request_uuid"] for a, p in control.calls if a == "commit")
    assert reserve_uuid == commit_uuid


async def test_count_capable_provider_without_enabled_counting_keeps_full_context_reservation():
    # The provider can count, but this grant's alias does not have token-count enabled
    # (no zero-cost request price), so the request must still be admitted on the
    # conservative full-context bound rather than failing to reserve.
    control, provider = CountingControlPort(count_enabled=False), CountingProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        result = await client.post("/v1/messages", headers=_HEADERS, json=_BODY)

    assert result.status_code == 200
    assert [action for action, _ in control.calls] == ["authenticate", "reserve", "dispatch", "check", "settle"]
    assert provider.counted == 0 and provider.invocations == 1  # no separate count phase; single paid path
    paid_input = next(a for a in control.reserved_bounds[0]["amounts"] if a["component"] == "input_tokens")
    assert paid_input["units"] == _CONTEXT_WINDOW  # conservative full-context reservation


async def test_reserve_carries_the_retry_key_so_a_completed_retry_dedups_before_counting():
    control, provider = CountingControlPort(), CountingProviderPort()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(control, provider)), base_url="https://broker.invalid"
    ) as client:
        await client.post("/v1/messages", headers={**_HEADERS, "idempotency-key": "retry-1"}, json=_BODY)

    reserves = [payload for action, payload in control.calls if action == "reserve"]
    commits = [payload for action, payload in control.calls if action == "commit"]
    assert len(reserves) == 1 and len(commits) == 1
    # The single reservation carries the caller idempotency identity, so a completed
    # retry deduplicates at reserve before the provider is ever counted.
    assert reserves[0].get("caller_key_hmac")
    # Commit is a mid-request effect, not a dedup point, and never carries a retry key.
    assert "caller_key_hmac" not in commits[0]
    assert "a routine short prompt" not in json.dumps(control.calls)
