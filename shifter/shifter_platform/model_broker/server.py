"""Participant listener: authenticated, budgeted, fenced provider streaming."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime

from shared.model_access import ContractError
from shared.model_access.credentials import ModelAccessAuthorization
from shared.model_access.diagnostics import isolate_transport_diagnostics
from shared.model_access.http import ASGIScope, Receive, ResponseWriter, Send, body, headers, json_response
from shared.model_access.messages import MAX_MESSAGE_BYTES, CountTokensRequest, JsonObject, parse_messages, strict_json
from shared.model_access.traffic import TrafficBudget

from .control import ControlClient
from .execution import BrokerInvocation, BrokerRequest
from .providers import ProviderRegistry

_CREDENTIAL_UNAVAILABLE = "credential.unavailable"


# Closed participant error codes with an actionable transport meaning, mapped to a
# fixed status and Messages envelope type so the pinned client backs off, fails or
# retries correctly instead of looping on a mislabelled provider outcome.
_ERROR_ENVELOPE = {
    "http.rate_limited": (429, "rate_limit_error"),
    "credential.rate_limited": (429, "rate_limit_error"),
    "provider.rate_limited": (429, "rate_limit_error"),
    _CREDENTIAL_UNAVAILABLE: (401, "authentication_error"),
    "provider.invalid_request": (400, "invalid_request_error"),
    "provider.unavailable": (503, "api_error"),
}


def _broker_error(code: str) -> tuple[int, str]:
    """Map a closed participant error to its fixed transport status and envelope type."""
    return _ERROR_ENVELOPE.get(code, (409, "invalid_request_error"))


def _broker_route(scope: ASGIScope) -> tuple[str, bool]:
    """Admit only the exact participant and access routes."""
    path = scope["path"]
    allowed = {"/v1/messages", "/v1/messages/count_tokens", "/v1/access/exchange", "/v1/access/refresh"}
    models = scope["method"] == "GET" and path == "/v1/models"
    if not models and (scope["method"] != "POST" or path not in allowed):
        raise ContractError("broker.invalid_route")
    return path, models


class BrokerApplication:
    """No generic proxy, credential issuance or public control surface."""

    def __init__(
        self,
        *,
        control: ControlClient,
        providers: ProviderRegistry,
        fingerprint_key: bytes,
        key_version: str,
        previous_keys: dict[str, bytes] | None = None,
    ) -> None:
        isolate_transport_diagnostics()
        if len(fingerprint_key) < 32:
            raise ValueError("broker fingerprint key needs at least 256 bits")
        self.control = control
        self.providers = providers
        self.fingerprint_key = fingerprint_key
        self.key_version = key_version
        self.previous_keys = dict(previous_keys or {})
        if (
            key_version in self.previous_keys
            or len(self.previous_keys) > 8
            or any(len(key) < 32 for key in self.previous_keys.values())
        ):
            raise ValueError("invalid retained broker fingerprint keys")
        self.draining = False
        self.ingress_budget = TrafficBudget()
        self.drain = asyncio.Event()

    def begin_drain(self) -> None:
        """Stop admission and wake every in-flight transport at signal receipt."""
        self.draining = True
        self.drain.set()

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, ResponseWriter(send))

    async def _http(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        """Map bounded routing failures to fixed participant-safe envelopes."""
        started_at = asyncio.get_running_loop().time()
        try:
            path = scope.get("path", "")
            if scope.get("query_string"):
                raise ContractError("broker.invalid_route")
            if scope["method"] == "GET" and path in {"/health/live", "/health/ready"}:
                healthy = path.endswith("live") or await self._ready()
                await json_response(send, 200 if healthy else 503, {"ready": healthy})
            else:
                # Upload and private calls each have bounded I/O. The invocation
                # alone owns the absolute deadline once a response can start.
                await self._post(scope, receive, send, started_at=started_at)
        except ContractError as exc:
            status, category = _broker_error(exc.code)
            await _error(send, status, category, exc.code)
        except (ValueError, TimeoutError):
            await _error(send, 400, "invalid_request_error", "broker.invalid_request")
        except Exception:
            await _error(send, 503, "api_error", "broker.unavailable")

    async def _ready(self) -> bool:
        """Readiness requires usable workload authority and a responsive Engine."""
        if self.draining:
            return False
        try:
            return (await self.control.call("ready", {})).get("ready") is True
        except Exception:
            return False

    async def _post(self, scope: ASGIScope, receive: Receive, send: Send, *, started_at: float) -> None:
        """Admit only JSON access and Messages operations on fixed routes."""
        if self.draining:
            raise ContractError("broker.draining")
        path, models = _broker_route(scope)
        request_headers = headers(scope)
        peer = (scope.get("client") or ("",))[0]
        self.ingress_budget.consume(peer)
        if models:
            await self._models(request_headers, peer, send)
            return
        if request_headers.get("content-type", "").split(";")[0] != "application/json":
            raise ContractError("broker.invalid_content_type")
        if path.startswith("/v1/access/"):
            if "authorization" in request_headers or "x-api-key" in request_headers:
                raise ContractError(_CREDENTIAL_UNAVAILABLE)
            raw = await body(receive, limit=4096)
            await self._exchange(path, peer, raw, send)
            return
        raw = await body(receive, limit=MAX_MESSAGE_BYTES)
        request = await self._authorize_message(path, peer, raw, request_headers, started_at=started_at)
        await self._invoke(request, receive, send)

    async def _invoke(self, request: BrokerRequest, receive: Receive, send: Send) -> None:
        """Resolve only this grant's fixed provider before invoking its budgeted call."""
        async with asyncio.timeout_at(request.deadline):
            shard = request.authority.aliases[request.message.model]
            if shard.credential_ref.reference.startswith("source:"):
                projection = await self.control.call(
                    "source",
                    {"token": request.token, "transport_peer": request.peer, "logical_alias": request.message.model},
                )
                provider = self.providers.build_projected(shard, request.authority.limits, projection)
            else:
                provider = self.providers.build(shard, request.authority.limits)
        # End the resolution timer before installing the invocation's timer.
        # Overlapping cancellation skips its bounded terminal error response.
        await BrokerInvocation(self.control, provider, request, receive, send, drain=self.drain).run()

    async def _models(self, request_headers: dict[str, str], peer: str, send: Send) -> None:
        """List current logical aliases without exposing provider inventory."""
        authority = ModelAccessAuthorization.model_validate(
            await self.control.call("authenticate", {"token": self._token(request_headers), "transport_peer": peer})
        )
        await json_response(
            send,
            200,
            {
                "data": [{"id": alias, "type": "model", "display_name": alias} for alias in sorted(authority.aliases)],
                "has_more": False,
            },
        )

    async def _authorize_message(
        self, path: str, peer: str, raw: bytes, request_headers: dict[str, str], *, started_at: float
    ) -> BrokerRequest:
        """Authenticate and enforce the logical model's declared capabilities."""
        if request_headers.get("anthropic-version") != "2023-06-01" or request_headers.get("anthropic-beta"):
            raise ContractError("messages.unsupported_version")
        token = self._token(request_headers)
        authority = ModelAccessAuthorization.model_validate(
            await self.control.call("authenticate", {"token": token, "transport_peer": peer})
        )
        count_only = path.endswith("count_tokens")
        message = parse_messages(raw, count_only=count_only, limits=authority.limits)
        if message.model not in authority.aliases:
            raise ContractError("messages.alias_unavailable")
        required = "token-count" if count_only else "messages"
        if required not in authority.aliases[message.model].capabilities:
            raise ContractError("messages.capability_unavailable")
        return BrokerRequest(
            message,
            authority,
            token,
            peer,
            count_only,
            self._retry_fields(request_headers, message, count_only=count_only),
            min(
                started_at + min(120, authority.limits.max_request_seconds),
                asyncio.get_running_loop().time() + (authority.hard_expires_at - datetime.now(UTC)).total_seconds(),
            ),
        )

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                self.begin_drain()
                await self.control.close()
                await self.providers.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    def _token(request_headers: dict[str, str]) -> str:
        api_key = request_headers.get("x-api-key", "")
        authorization = request_headers.get("authorization", "")
        if "x-api-key" in request_headers and "authorization" in request_headers:
            raise ContractError(_CREDENTIAL_UNAVAILABLE)
        token = api_key or (authorization[7:] if authorization.startswith("Bearer ") else "")
        if len(token) != 80:
            raise ContractError(_CREDENTIAL_UNAVAILABLE)
        return token

    async def _exchange(self, path: str, peer: str, raw: bytes, send: Send) -> None:
        payload = strict_json(raw, limit=4096)
        if set(payload) != {"token"} or not isinstance(payload["token"], str) or len(payload["token"]) != 80:
            raise ContractError(_CREDENTIAL_UNAVAILABLE)
        result = await self.control.call(path.rsplit("/", 1)[1], {"token": payload["token"], "transport_peer": peer})
        await json_response(send, 200, result)

    def _retry_fields(
        self, request_headers: dict[str, str], message: CountTokensRequest, *, count_only: bool
    ) -> JsonObject:
        key = request_headers.get("idempotency-key")
        if key is None:
            return {}
        if not 1 <= len(key) <= 128 or not key.isascii():
            raise ContractError("messages.invalid_retry_key")
        intent = json.dumps(
            {"count_only": count_only, "body": message.model_dump(mode="json")}, sort_keys=True, separators=(",", ":")
        ).encode()

        def digest(data: bytes) -> str:
            """Fingerprint only bounded request metadata under the active key."""
            return hmac.new(self.fingerprint_key, data, hashlib.sha256).hexdigest()

        return {
            "caller_key_hmac": digest(b"key\0" + key.encode()),
            "intent_fingerprint_hmac": digest(b"intent\0" + intent),
            "key_version": self.key_version,
            "prior_caller_key_hmacs": [
                hmac.new(secret, b"key\0" + key.encode(), hashlib.sha256).hexdigest()
                for secret in self.previous_keys.values()
            ],
            "prior_intent_fingerprint_hmacs": [
                hmac.new(secret, b"intent\0" + intent, hashlib.sha256).hexdigest()
                for secret in self.previous_keys.values()
            ],
            "retained_key_versions": list(self.previous_keys),
        }


async def _error(send: Send, status: int, category: str, message: str) -> None:
    """Emit the fixed Messages error envelope without exception diagnostics."""
    from contextlib import suppress

    with suppress(OSError, TimeoutError):
        async with asyncio.timeout(1):
            await json_response(send, status, {"type": "error", "error": {"type": category, "message": message}})
