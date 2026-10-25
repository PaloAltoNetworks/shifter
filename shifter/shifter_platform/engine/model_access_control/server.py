"""TLS control ASGI application with separate broker/provisioner authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from functools import partial
from typing import Protocol
from uuid import UUID

from engine.services import (
    RequestIdempotency,
    advance_model_call,
    authenticate_model_access,
    commit_model_call,
    exchange_model_enrollment,
    finish_model_call,
    issue_model_enrollment,
    model_source_execution,
    refresh_model_access,
    reserve_model_call,
)
from shared.model_access import ContractError
from shared.model_access.diagnostics import isolate_transport_diagnostics
from shared.model_access.http import ASGIScope, Receive, ResponseWriter, Send, body, headers, json_response
from shared.model_access.messages import JsonObject, strict_json
from shared.model_access.traffic import TrafficBudget

from .schemas import (
    AdvanceRequest,
    CommitRequest,
    EnrollmentRequest,
    FinishRequest,
    ReservationRequest,
    SourceExecutionRequest,
    TokenRequest,
)
from .work import ControlWork

_INVALID_ROUTE = "control.invalid_route"


def _control_error_status(code: str) -> int:
    """Map closed control errors to fixed transport statuses."""
    if code in {"control.unauthorized", "credential.unavailable"}:
        return 401
    if code == "control.busy":
        return 503
    return 409


def _control_route(scope: ASGIScope) -> str:
    """Accept only exact private POST routes."""
    path = scope.get("path", "")
    route = path.removeprefix("/control/v1/")
    if scope["method"] != "POST" or route not in _HANDLERS or path != f"/control/v1/{route}":
        raise ContractError(_INVALID_ROUTE)
    return route


class IdentityVerifier(Protocol):
    """Verify broker identity or the provisioner audience for one enrollment."""

    def __call__(self, assertion: str, *, operation_id: UUID | None) -> None: ...


class ControlApplication:
    """Only authenticated workload callers can reach Engine effects."""

    def __init__(self, *, verify_identity: IdentityVerifier, ready: Callable[[], bool]) -> None:
        isolate_transport_diagnostics()
        self.verify_identity = verify_identity
        self.ready = ready
        self.work = ControlWork()
        self.credential_budget = TrafficBudget(per_key=600, total=1200)

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        send = ResponseWriter(send)
        try:
            if scope["type"] != "http":
                return
            await self._route(scope, receive, send)
        except ContractError as exc:
            await json_response(send, _control_error_status(exc.code), {"error": exc.code})
        except (ValueError, TimeoutError):
            await json_response(send, 400, {"error": "control.invalid_request"})
        except Exception:
            # No raw exception logging: request arguments can contain credentials.
            await json_response(send, 503, {"error": "control.unavailable"})

    async def _route(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        """Serve private health probes or pass a query-free control request onward."""
        path = scope.get("path", "")
        if scope.get("query_string"):
            raise ContractError(_INVALID_ROUTE)
        if scope["method"] == "GET" and path in {"/health/live", "/health/ready"}:
            async with asyncio.timeout(2):
                healthy = path.endswith("live") or await self.work.run(self.ready, lifecycle=True, database=True)
            await json_response(send, 200 if healthy else 503, {"ready": healthy})
        else:
            await self._post(scope, receive, send)

    async def _post(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        """Validate a closed control request before authenticating its workload."""
        route = _control_route(scope)
        request_headers = headers(scope)
        if request_headers.get("content-type", "").split(";")[0] != "application/json":
            raise ContractError("control.invalid_content_type")
        payload = strict_json(await body(receive, limit=65_536), limit=65_536)
        enrollment = EnrollmentRequest.model_validate(payload) if route == "enroll" else None
        lifecycle = route in {"advance", "commit", "finish", "ready"}
        if route in {"enroll", "exchange", "refresh"}:
            self.credential_budget.consume((scope.get("client") or ("",))[0])
        async with asyncio.timeout(2):
            await self.work.run(
                partial(
                    self.verify_identity,
                    request_headers.get("authorization", ""),
                    operation_id=enrollment.operation_id if enrollment else None,
                ),
                lifecycle=lifecycle,
            )
            result = await self._authorized_result(route, payload, lifecycle=lifecycle)
        await json_response(send, 200, result)

    async def _authorized_result(self, route: str, payload: JsonObject, *, lifecycle: bool) -> JsonObject:
        """Run a checked control action under its bounded worker lane."""
        if route == "ready":
            if payload:
                raise ValueError
            return {"ready": await self.work.run(self.ready, lifecycle=True, database=True)}
        return await self.work.run(partial(self._dispatch, route, payload), lifecycle=lifecycle, database=True)

    @staticmethod
    def _dispatch(route: str, payload: JsonObject) -> JsonObject:
        handler = _HANDLERS.get(route)
        if handler is None:
            raise ContractError(_INVALID_ROUTE)
        return handler(payload)


def _enroll(payload: JsonObject) -> JsonObject:
    """Issue a guest enrollment for the authenticated operation generation."""
    request = EnrollmentRequest.model_validate(payload)
    enrollment = issue_model_enrollment(**request.model_dump())
    return {
        "grant_id": str(enrollment.grant_id),
        "enrollment_token": enrollment.enrollment_token.get_secret_value(),
        "expires_at": enrollment.expires_at.isoformat(),
    }


def _token_operation(payload: JsonObject, *, route: str) -> JsonObject:
    """Exchange, refresh or authenticate a peer-bound guest credential."""
    request = TokenRequest.model_validate(payload)
    token, peer = request.token.get_secret_value(), request.transport_peer
    if route == "authenticate":
        return authenticate_model_access(token=token, transport_peer=peer).model_dump(mode="json")
    operation = exchange_model_enrollment if route == "exchange" else refresh_model_access
    pair = operation(token=token, transport_peer=peer)
    return {
        "access_token": pair.access_token.get_secret_value(),
        "refresh_token": pair.refresh_token.get_secret_value(),
        "access_expires_at": pair.access_expires_at.isoformat(),
        "hard_expires_at": pair.hard_expires_at.isoformat(),
    }


def _reserve(payload: JsonObject) -> JsonObject:
    """Reserve a provider billing bound through Engine's accounting boundary."""
    request = ReservationRequest.model_validate(payload)
    reservation = reserve_model_call(
        token=request.token.get_secret_value(),
        transport_peer=request.transport_peer,
        request_uuid=request.request_uuid,
        logical_alias=request.logical_alias,
        billing_bound=request.billing_bound,
        idempotency=RequestIdempotency(
            caller_key_hmac=request.caller_key_hmac,
            intent_fingerprint_hmac=request.intent_fingerprint_hmac,
            key_version=request.key_version,
            prior_caller_key_hmacs=request.prior_caller_key_hmacs,
            prior_intent_fingerprint_hmacs=request.prior_intent_fingerprint_hmacs,
            retained_key_versions=request.retained_key_versions,
        ),
    )
    return {**asdict(reservation), "request_uuid": str(reservation.request_uuid)}


def _advance(payload: JsonObject) -> JsonObject:
    """Advance only the request's authenticated dispatch lease."""
    request = AdvanceRequest.model_validate(payload)
    return advance_model_call(
        **request.model_dump(exclude={"token", "dispatch_token"}),
        token=request.token.get_secret_value(),
        dispatch_token=request.dispatch_token.get_secret_value(),
    )


def _commit(payload: JsonObject) -> JsonObject:
    """Commit a counted request's proven input/output spend before paid dispatch."""
    request = CommitRequest.model_validate(payload)
    return commit_model_call(
        token=request.token.get_secret_value(),
        transport_peer=request.transport_peer,
        request_uuid=request.request_uuid,
        billing_bound=request.billing_bound,
    )


def _finish(payload: JsonObject) -> JsonObject:
    """Settle usage or preserve uncertainty through the closed terminal actions."""
    request = FinishRequest.model_validate(payload)
    return finish_model_call(request_uuid=request.request_uuid, action=request.action, usage=request.usage)


def _source(payload: JsonObject) -> JsonObject:
    """Project execution credentials only for an authenticated model grant."""
    request = SourceExecutionRequest.model_validate(payload)
    return model_source_execution(
        token=request.token.get_secret_value(),
        transport_peer=request.transport_peer,
        logical_alias=request.logical_alias,
    )


_HANDLERS: dict[str, Callable[[JsonObject], JsonObject]] = {
    "ready": lambda payload: {},
    "source": _source,
    "enroll": _enroll,
    "exchange": partial(_token_operation, route="exchange"),
    "refresh": partial(_token_operation, route="refresh"),
    "authenticate": partial(_token_operation, route="authenticate"),
    "reserve": _reserve,
    "advance": _advance,
    "commit": _commit,
    "finish": _finish,
}
