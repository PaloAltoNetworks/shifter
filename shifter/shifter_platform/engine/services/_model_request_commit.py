"""Commit the proven input/output spend to a counted request before paid dispatch (M07).

A counting paid request is admitted with a free count bound (rate and concurrency
held, zero spend) so a completed retry deduplicates before the provider is ever
counted. After the provider-proven count this narrows the request's input units to
that count, adds the output ceiling, checks every spend account against the
immutable price snapshot, and replaces the bound so settlement matches the paid
usage. It upgrades a freshly dispatched count reservation exactly once and never
touches a settled request.

Canonical lock order matches reserve and dispatch: allocation/grant and authority
before the request row and its account postings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.model_access import BillingBound, ContractError
from shared.model_access.core_models import BillingComponent

from ._model_request_accounting import _SPEND_UNIT, _conservative_charge, _load_snapshot, _recheck_authority
from ._model_request_lifecycle import (
    _assert_allocation_live,
    _assert_grant_current,
    _assert_request_current,
    _lifecycle_audit,
    _locked_postings,
)

if TYPE_CHECKING:
    from engine.models import ModelRequestReservation

_COMMIT_STATE = "request.commit_state"


def commit_request_spend(*, request_uuid: UUID, billing_bound: BillingBound, now: datetime | None = None) -> int:
    """Add the proven input/output spend hold to a counted reservation, atomically."""
    from engine.models import ModelAllocation, ModelPendingGrant, ModelRequestReservation

    moment = now or datetime.now(UTC)
    with transaction.atomic():
        reservation = ModelRequestReservation.objects.get(request_uuid=request_uuid)
        allocation = ModelAllocation.objects.select_for_update().get(pk=reservation.allocation_id)
        _assert_allocation_live(allocation, moment)
        _assert_request_current(reservation, moment)
        _assert_grant_current(ModelPendingGrant, reservation)
        _recheck_authority(allocation)
        reservation = ModelRequestReservation.objects.select_for_update().get(pk=reservation.pk)
        if reservation.state != "dispatched" or set(reservation.billed_components or ()) != {
            BillingComponent.REQUEST.value
        }:
            # Commit upgrades a freshly dispatched count reservation exactly once.
            raise ContractError(_COMMIT_STATE)
        catalog, effective = _load_snapshot(allocation)
        currency, upper_charge = _conservative_charge(
            catalog, reservation.logical_alias, billing_bound, moment, effective, reservation.shard["shard_id"]
        )
        _apply_spend_hold(reservation, currency, upper_charge)
        reservation.billing_bound = billing_bound.model_dump(mode="json")
        reservation.billed_components = sorted({amount.component.value for amount in billing_bound.amounts})
        reservation.canonical_request_cost = upper_charge
        reservation.save(update_fields=["billing_bound", "billed_components", "canonical_request_cost", "updated_at"])
        _lifecycle_audit(reservation, "MODEL_REQUEST_RESERVE", f"commit cost={upper_charge}")
        return upper_charge


def _apply_spend_hold(reservation: ModelRequestReservation, currency: str, upper_charge: int) -> None:
    """Admit against every spend account, then place the proven hold on each posting."""
    holds = [(posting, account) for posting, account in _locked_postings(reservation) if account.dimension == "spend"]
    for _posting, account in holds:
        if account.currency != currency or account.unit != _SPEND_UNIT:
            raise ContractError("request.currency_mismatch")
        if account.spent + account.reserved + upper_charge > account.limit:
            raise ContractError("request.budget_exceeded")
    for posting, account in holds:
        account.reserved += upper_charge
        account.save(update_fields=["reserved"])
        posting.held = upper_charge
        posting.save(update_fields=["held"])
