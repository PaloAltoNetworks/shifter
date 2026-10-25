"""Model invocation through fixed provider origins and revision-bound identities."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote

import httpx

from shared.model_access import BillingBound, ContractError
from shared.model_access.core_models import AccessLimits, BillingComponent, ModelShard
from shared.model_access.messages import (
    MAX_RESPONSE_BYTES,
    CountTokensRequest,
    JsonObject,
    MessagesRequest,
    strict_json,
)
from shared.model_access.provider import (
    BillingAmount,
    CancellationResult,
    ModelProviderAdapter,
    ProviderAdapterRegistry,
    ProviderCapabilities,
    ProviderUsage,
    VerifiedUsage,
)
from shared.model_access.provider_runtime import ProviderInventory, ProviderTarget, SourceExecutionProjection

from .egress import provider_proxy
from .errors import NoBillableEffect
from .provider_credentials import ProviderCredentials
from .provider_usage import (
    StreamUsage,
    bedrock_events,
    encode_sse,
    usage_from_message,
    validate_message_response,
    vertex_events,
)

# Bounded upstream transport controls. The absolute request/grant deadline in
# BrokerInvocation is the total cap; these bound each transport phase separately so
# a useful streamed coding response is not cut at a five-second read, while an idle
# upstream still cannot stall a worker slot indefinitely. Tune from observed client
# and provider behavior (#2334); never disable a control to make streaming pass.
_STREAM_IDLE_SECONDS = 30.0
_CONNECT_SECONDS = 2.0
_WRITE_SECONDS = 5.0
_POOL_SECONDS = 1.0

_INVALID_REQUEST = "provider.invalid_request"
_INPUT_LIMIT = "messages.input_limit"

# Provider HTTP statuses that carry an actionable participant meaning. Everything
# else, including auth failures that are the deployment's and not the participant's,
# normalizes to a bounded 'unavailable' so no provider body, header or request id
# leaks and the pinned client is not driven into a credential-rejection retry loop.
_PROVIDER_STATUS_CODES = {
    429: "provider.rate_limited",
    400: _INVALID_REQUEST,
    413: _INVALID_REQUEST,
    422: _INVALID_REQUEST,
}


def _provider_error(status_code: int) -> ContractError:
    """Classify a non-200 provider status into a bounded, body-free participant error.

    Mirrors the ``ProviderError`` category vocabulary: rate-limited preserves client
    backoff, malformed-request statuses stay client-visible, and authentication or
    server failures surface as unavailable without exposing provider diagnostics.
    """
    return ContractError(_PROVIDER_STATUS_CODES.get(status_code, "provider.unavailable"))


@dataclass
class ProviderResponse:
    """Streaming content plus usage populated only after a complete upstream reply."""

    content_type: str
    chunks: AsyncIterator[bytes]
    usage: ProviderUsage | None = None


class ProviderRegistry:
    """Exact shard inventory; no provider/model fallback on failure."""

    def __init__(
        self, *, inventory: ProviderInventory, credentials: ProviderCredentials, client: httpx.AsyncClient | None = None
    ) -> None:
        self.targets = {target.shard_id: target for target in inventory.targets}
        self.credentials = credentials
        self.client = client or httpx.AsyncClient(
            proxy=provider_proxy(),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(
                _STREAM_IDLE_SECONDS, connect=_CONNECT_SECONDS, pool=_POOL_SECONDS, write=_WRITE_SECONDS
            ),
            limits=httpx.Limits(max_connections=128),
        )

    def build(self, shard: ModelShard, limits: AccessLimits) -> MessagesProvider:
        target = self.targets.get(shard.shard_id)
        if target is None:
            raise ContractError("provider.target_unavailable")
        target.bind(shard)
        if not {"input_tokens", "output_tokens"}.issubset(shard.billing_components):
            raise ContractError("provider.billing_unsupported")
        registry = ProviderAdapterRegistry(
            {
                target.provider: lambda bound_shard: MessagesProvider(
                    target=target.bind(bound_shard),
                    limits=limits,
                    credentials=self.credentials,
                    client=self.client,
                )
            }
        )
        return cast(MessagesProvider, registry.build(shard))

    def build_projected(self, shard: ModelShard, limits: AccessLimits, projection: object) -> MessagesProvider:
        """Bind transient control credentials to this exact allocation shard."""
        try:
            value = SourceExecutionProjection.model_validate(projection)
            target = value.target.bind(shard)
            credential = strict_json(value.credential.encode(), limit=32768) if value.credential else None
        except ValueError:
            raise ContractError("provider.invalid_projection") from None
        if not {"input_tokens", "output_tokens"}.issubset(shard.billing_components):
            raise ContractError("provider.billing_unsupported")
        return MessagesProvider(
            target=target,
            limits=limits,
            credentials=ProviderCredentials(credential=credential),
            client=self.client,
            upstream_provider=value.upstream_provider,
        )

    async def close(self) -> None:
        await self.client.aclose()


class MessagesProvider(ModelProviderAdapter):
    """Text/local-tool protocol with conservative full-context spend reservation."""

    def __init__(
        self,
        *,
        target: ProviderTarget,
        limits: AccessLimits,
        credentials: ProviderCredentials,
        client: httpx.AsyncClient,
        upstream_provider: str = "",
    ) -> None:
        self.target, self.limits, self.credentials, self.client = target, limits, credentials, client
        self.upstream_provider = upstream_provider

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            adapter_id=self.target.provider,
            protocols=("anthropic-messages/2023-06-01",),
            models=(self.target.model,),
            capabilities=("messages",) if self.target.provider == "openrouter-v1" else ("messages", "token-count"),
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
            token_counting=self.target.provider != "openrouter-v1",
            cancellation=False,
            completion_horizon_seconds=900,
        )

    @staticmethod
    def normalize_usage(provider_result: object) -> ProviderUsage:
        if not isinstance(provider_result, dict):
            raise ContractError("provider.invalid_usage")
        return usage_from_message(provider_result)

    @staticmethod
    def cancel(provider_request_id: str) -> CancellationResult:
        # Closing a stream ends our transport; it does not prove a provider job
        # stopped. Preserve the conservative liability through reconciliation.
        from shared.model_access.provider import CancellationDisposition

        return CancellationResult(disposition=CancellationDisposition.UNSUPPORTED)

    def billing_bound(self, *, model: str, features: tuple[str, ...], request_bytes: int) -> BillingBound:
        """Implement the provider contract using the deployment's conservative limits."""
        if model != self.target.model or set(features) - {"messages", "token-count"}:
            raise ContractError("provider.capability_mismatch")
        if request_bytes > self.limits.max_request_bytes:
            raise ContractError("messages.too_large")
        return self._billing_bound(count_only=features == ("token-count",), output_limit=self.limits.max_output_tokens)

    def message_billing_bound(
        self, message: CountTokensRequest, *, count_only: bool, input_tokens: int | None = None
    ) -> BillingBound:
        """Reserve output by the request's limit and input by a proven count when known."""
        output_limit = message.max_tokens if isinstance(message, MessagesRequest) else self.limits.max_output_tokens
        return self._billing_bound(count_only=count_only, output_limit=output_limit, input_tokens=input_tokens)

    def _billing_bound(self, *, count_only: bool, output_limit: int, input_tokens: int | None = None) -> BillingBound:
        """Count endpoints are free but still consume rate and concurrency capacity.

        A provider-proven ``input_tokens`` narrows the input reservation so routine
        small prompts are not denied; absent that proof the full physical context
        window is the only safe conservative bound.
        """
        input_units = self.target.context_window_tokens if input_tokens is None else input_tokens
        amounts = (
            [(BillingComponent.REQUEST, 1)]
            if count_only
            else [
                (BillingComponent.INPUT_TOKENS, input_units),
                (BillingComponent.OUTPUT_TOKENS, output_limit),
            ]
        )
        return BillingBound(
            amounts=tuple(
                BillingAmount(component=key, units=value, maximum_charge_micro_units=0) for key, value in amounts
            )
        )

    def _request(self, message: CountTokensRequest, *, count_only: bool) -> tuple[str, bytes]:
        payload = message.model_dump(mode="json", exclude_none=True)
        payload.pop("model", None)
        if count_only:
            for field in ("max_tokens", "stream", "temperature", "top_p", "top_k", "stop_sequences"):
                payload.pop(field, None)
        if self.target.provider == "vertex-v1":
            url = _vertex_request(self.target, payload, count_only=count_only)
        elif self.target.provider == "bedrock-v1":
            output_limit = message.max_tokens if isinstance(message, MessagesRequest) else self.limits.max_output_tokens
            url, payload = _bedrock_request(self.target, payload, count_only=count_only, output_limit=output_limit)
        elif self.target.provider == "anthropic-v1":
            payload["model"] = self.target.model
            url = "https://api.anthropic.com/v1/messages" + ("/count_tokens" if count_only else "")
        elif self.target.provider == "openai-v1":
            from .openai_messages import responses_request

            payload = responses_request(payload, model=self.target.model, count_only=count_only)
            url = "https://api.openai.com/v1/responses" + ("/input_tokens" if count_only else "")
        elif self.target.provider == "openrouter-v1":
            url = self._routed_request(payload, count_only=count_only)
        else:
            raise ContractError("provider.transport_unsupported")
        return url, json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()

    def _routed_request(self, payload: JsonObject, *, count_only: bool) -> str:
        """Pin the routed provider and prohibit fallback or data collection."""
        if count_only or not self.upstream_provider:
            raise ContractError("provider.count_unsupported")
        payload["model"] = self.target.model
        payload["provider"] = {
            "only": [self.upstream_provider],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        }
        return "https://openrouter.ai/api/v1/messages"

    @asynccontextmanager
    async def _upstream(
        self, message: CountTokensRequest, *, count_only: bool, before_transport: Callable[[], Awaitable[str]]
    ) -> AsyncIterator[httpx.Response]:
        try:
            url, raw = self._request(message, count_only=count_only)
            headers = await self.credentials.headers(self.target, url=url, body=raw)
            deadline = datetime.fromisoformat(await before_transport())
            if datetime.now(UTC) + timedelta(seconds=4) >= deadline:
                raise ValueError("transport lease expired")
        except Exception:
            raise NoBillableEffect("provider.transport_lease_unavailable", count_only=count_only) from None
        async with self.client.stream("POST", url, content=raw, headers=headers) as response:
            if response.status_code != 200:
                # Normalize to a bounded category without reflecting provider bodies or
                # automatically retrying a call that might already have incurred an effect.
                raise _provider_error(response.status_code)
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ContractError("provider.encoding_unsupported")
            yield response

    @staticmethod
    async def _json(response: httpx.Response) -> JsonObject:
        raw = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16_384):
            if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ContractError("provider.response_limit")
            raw.extend(chunk)
        return strict_json(bytes(raw), limit=MAX_RESPONSE_BYTES)

    async def _count(self, message: CountTokensRequest, before_transport: Callable[[], Awaitable[str]]) -> int:
        async with self._upstream(message, count_only=True, before_transport=before_transport) as response:
            value = await self._json(response)
        key = "inputTokens" if self.target.provider == "bedrock-v1" else "input_tokens"
        tokens = value.get(key)
        if type(tokens) is not int or not 0 <= tokens <= self.target.context_window_tokens:
            raise ContractError("provider.invalid_count")
        return tokens

    async def _validated_count(
        self, message: CountTokensRequest, *, count_only: bool, before_transport: Callable[[], Awaitable[str]]
    ) -> int:
        """Check the free count and context bounds before attempting billable work."""
        if self.target.provider == "openrouter-v1":
            if count_only:
                raise NoBillableEffect("provider.count_unsupported", count_only=True)
            # This provider offers no documented free counting endpoint. The
            # full physical context is the only safe pre-dispatch input bound.
            # Smaller input envelopes fail closed; no estimate becomes a count.
            if self.target.context_window_tokens > self.limits.max_input_tokens:
                raise NoBillableEffect(_INPUT_LIMIT, count_only=False)
            return self.target.context_window_tokens
        # The count is covered by the request's existing reservation and lease.
        # It cannot mint a second grant or bypass rate/concurrency admission.
        try:
            tokens = await self._count(message, before_transport)
        except Exception:
            # The fixed count endpoint is free, and no invocation was attempted.
            raise NoBillableEffect("provider.count_unavailable", count_only=count_only) from None
        if tokens > self.limits.max_input_tokens:
            raise NoBillableEffect(_INPUT_LIMIT, count_only=count_only)
        if not count_only:
            if not isinstance(message, MessagesRequest):
                raise NoBillableEffect("messages.unsupported_request", count_only=False)
            if tokens + message.max_tokens > self.target.context_window_tokens:
                raise NoBillableEffect("messages.context_limit", count_only=False)
        return tokens

    async def count(self, message: CountTokensRequest, *, before_transport: Callable[[], Awaitable[str]]) -> int:
        """Prove the request's input token count through the fixed free count endpoint."""
        return await self._validated_count(message, count_only=False, before_transport=before_transport)

    def _accept_precount(self, message: CountTokensRequest, precounted: int) -> int:
        """Trust only this request's own proven count, still bounded by the physical context."""
        if not isinstance(message, MessagesRequest):
            raise NoBillableEffect("messages.unsupported_request", count_only=False)
        if not 0 <= precounted <= self.limits.max_input_tokens:
            raise NoBillableEffect("messages.input_limit", count_only=False)
        if precounted + message.max_tokens > self.target.context_window_tokens:
            raise NoBillableEffect("messages.context_limit", count_only=False)
        return precounted

    @asynccontextmanager
    async def invoke(
        self,
        message: CountTokensRequest,
        *,
        count_only: bool,
        before_transport: Callable[[], Awaitable[str]],
        precounted: int | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        if precounted is None:
            tokens = await self._validated_count(message, count_only=count_only, before_transport=before_transport)
        else:
            tokens = self._accept_precount(message, precounted)
        if count_only:

            async def counted() -> AsyncIterator[bytes]:
                """Return only the normalized free token count."""
                yield json.dumps({"input_tokens": tokens}).encode()

            yield ProviderResponse(
                "application/json",
                counted(),
                ProviderUsage(
                    items=(VerifiedUsage(component=BillingComponent.REQUEST, units=0, provider_verified=True),)
                ),
            )
            return
        async with self._upstream(message, count_only=False, before_transport=before_transport) as response:
            assert isinstance(message, MessagesRequest)

            async def chunks() -> AsyncIterator[bytes]:
                """Normalize each response and publish usage only at completion."""
                if message.stream:
                    tracker = StreamUsage()
                    events = self._stream_events(response)
                    async for event in events:
                        tracker.observe(event)
                        yield encode_sse(event)
                    result.usage = tracker.result()
                else:
                    value = await self._json(response)
                    if self.target.provider == "openai-v1":
                        from .openai_messages import response_message

                        value = response_message(value, model=self.target.model)
                    else:
                        validate_message_response(value)
                    result.usage = usage_from_message(value)
                    yield json.dumps(value, separators=(",", ":")).encode()

            result = ProviderResponse("text/event-stream" if message.stream else "application/json", chunks())
            yield result

    def _stream_events(self, response: httpx.Response) -> AsyncIterator[JsonObject]:
        """Decode the configured provider's stream into Messages events."""
        if self.target.provider == "openai-v1":
            from .openai_messages import responses_events

            return responses_events(response.aiter_bytes(), model=self.target.model)
        decoder = bedrock_events if self.target.provider == "bedrock-v1" else vertex_events
        # Decoders bound individual events and the total stream. Do not coalesce
        # small frames here: an idle provider must not delay a completed SSE event.
        return decoder(response.aiter_bytes())


def _vertex_request(target: ProviderTarget, payload: JsonObject, *, count_only: bool) -> str:
    """Bind a Vertex request to its configured region, project and publisher model."""
    region = target.count_region if count_only else target.region
    hostname = (
        f"aiplatform.{region}.rep.googleapis.com" if region in {"us", "eu"} else f"{region}-aiplatform.googleapis.com"
    )
    model = "count-tokens" if count_only else target.model.rsplit("/", 1)[1]
    method = "streamRawPredict" if payload.get("stream") else "rawPredict"
    if count_only:
        payload["model"] = target.model.rsplit("/", 1)[1]
    else:
        payload["anthropic_version"] = "vertex-2023-10-16"
    return (
        f"https://{hostname}/v1/projects/{target.project}/locations/{region}"
        f"/publishers/anthropic/models/{model}:{method}"
    )


def _bedrock_request(
    target: ProviderTarget, payload: JsonObject, *, count_only: bool, output_limit: int
) -> tuple[str, JsonObject]:
    """Encode the fixed Bedrock invocation or free CountTokens request."""
    stream = bool(payload.pop("stream", False))
    payload["anthropic_version"] = "bedrock-2023-05-31"
    if count_only:
        method = "count-tokens"
        payload["max_tokens"] = output_limit
        prompt = json.dumps(payload, separators=(",", ":")).encode()
        payload = {"input": {"invokeModel": {"body": base64.b64encode(prompt).decode()}}}
    else:
        method = "invoke-with-response-stream" if stream else "invoke"
    url = f"https://bedrock-runtime.{target.region}.amazonaws.com/model/{quote(target.model, safe='')}/{method}"
    return url, payload
