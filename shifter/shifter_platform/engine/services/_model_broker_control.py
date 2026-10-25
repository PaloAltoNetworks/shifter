"""Authenticated grant-bound request effects behind the private control API."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.model_access import BillingBound, ContractError
from shared.model_access.provider import ProviderUsage

from ._model_credentials import authenticate_model_access
from ._model_request_accounting import RequestIdempotency, ReservationOutcome, reserve_request
from ._model_request_commit import commit_request_spend
from ._model_request_lifecycle import (
    charge_unknown,
    check_dispatch_lease,
    open_dispatch,
    release_before_dispatch,
    renew_continuation_lease,
    settle_request,
)


def reserve_model_call(
    *,
    token: str,
    transport_peer: str,
    request_uuid: UUID,
    logical_alias: str,
    billing_bound: BillingBound,
    idempotency: RequestIdempotency | None = None,
    now: datetime | None = None,
) -> ReservationOutcome:
    """Authentication and reservation share the generation/epoch lock transaction."""
    moment = now or timezone.now()
    with transaction.atomic():
        authority = authenticate_model_access(token=token, transport_peer=transport_peer, now=moment)
        return reserve_request(
            allocation_id=authority.allocation_id,
            request_uuid=request_uuid,
            logical_alias=logical_alias,
            billing_bound=billing_bound,
            idempotency=replace(idempotency or RequestIdempotency(), intent_contract_version="model-messages/v1"),
            now=moment,
        )


def advance_model_call(
    *,
    token: str,
    transport_peer: str,
    request_uuid: UUID,
    action: str,
    dispatch_token: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Each provider-effect lease must still belong to the authenticated guest."""
    from engine.models import ModelRequestReservation

    moment = now or timezone.now()
    with transaction.atomic():
        authority = authenticate_model_access(token=token, transport_peer=transport_peer, now=moment)
        reservation = ModelRequestReservation.objects.filter(
            request_uuid=request_uuid,
            allocation_id=authority.allocation_id,
            operation_id=authority.operation_id,
            grant_epoch=authority.grant_epoch,
        ).first()
        if reservation is None:
            raise ContractError("request.unavailable")
        if action == "dispatch":
            lease = open_dispatch(request_uuid=request_uuid, now=moment)
            return {"dispatch_token": lease.dispatch_token, "deadline": lease.dispatch_deadline.isoformat()}
        if action == "check":
            check_dispatch_lease(request_uuid=request_uuid, dispatch_token=dispatch_token, now=moment)
            return {"valid": True}
        if action == "continue":
            revision = renew_continuation_lease(request_uuid=request_uuid, now=moment)
            from engine.models import ModelDispatchLease

            continuation = ModelDispatchLease.objects.get(reservation=reservation)
            if continuation.continuation_deadline is None:
                raise ContractError("request.no_lease")
            return {"revision": revision, "deadline": continuation.continuation_deadline.isoformat()}
        raise ContractError("request.invalid_action")


def commit_model_call(
    *,
    token: str,
    transport_peer: str,
    request_uuid: UUID,
    billing_bound: BillingBound,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Commit the proven input/output spend hold to this guest's counted request."""
    from engine.models import ModelRequestReservation

    moment = now or timezone.now()
    with transaction.atomic():
        authority = authenticate_model_access(token=token, transport_peer=transport_peer, now=moment)
        reservation = ModelRequestReservation.objects.filter(
            request_uuid=request_uuid,
            allocation_id=authority.allocation_id,
            operation_id=authority.operation_id,
            grant_epoch=authority.grant_epoch,
        ).first()
        if reservation is None:
            raise ContractError("request.unavailable")
        return {
            "canonical_request_cost": commit_request_spend(
                request_uuid=request_uuid, billing_bound=billing_bound, now=moment
            )
        }


def finish_model_call(
    *,
    request_uuid: UUID,
    action: str,
    usage: ProviderUsage | None = None,
) -> dict[str, Any]:
    """Broker-only settlement survives guest revocation and preserves liabilities.

    This operation must only be reachable after workload authentication, never
    from a participant route. Guest revocation cannot prevent recording the cost
    of its already-dispatched request. No raw upstream error text is accepted.
    """
    if action == "settle" and usage is not None:
        return {"charge": settle_request(request_uuid=request_uuid, usage=usage)}
    if action == "unknown":
        charge_unknown(request_uuid=request_uuid, uncertainty_reason="broker_transport_unknown")
        return {"recorded": True}
    if action == "release":
        release_before_dispatch(request_uuid=request_uuid)
        return {"released": True}
    raise ContractError("request.invalid_action")
