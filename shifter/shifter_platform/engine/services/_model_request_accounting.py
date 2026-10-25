"""Engine-owned atomic request-budget reservation before provider effects (M04).

``reserve_request`` binds one request to its existing allocation generation, grant
epoch, alias/shard, immutable price snapshot and applicable account set, then
admits it only if every affected spend/rate/concurrency account satisfies
``spent + reserved + upper_charge <= limit`` inside a single transaction. The
conservative upper charge is computed server-side in integer micro-units from the
allocation's immutable price revision; the caller-supplied provider bound only
contributes unit counts. A shared account reached through overlapping selectors is
deduplicated and posted once. A strict body-free decision audit commits in the
same transaction, before any possibly billable provider effect.

Canonical lock order (extends the owner-first protocol of the allocation
services): (1) range/execution generation via the allocation row, (2) allocation
and grant epoch, (3) pinned sharing-authority fences, (4) every account/window
identity in stable canonical order, (5) the request row, with the strict
audit-chain lock acquired last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction

from shared.model_access import (
    AccountDimension,
    BillingBound,
    ContractError,
    ModelAccessCatalogV3,
    validate_catalog,
)
from shared.model_access.account_policy import (
    AccountPolicyProjection,
    ResolvedRequestAccounts,
    resolve_request_accounts,
)
from shared.model_access.core_models import (
    AccountDefinition,
    AccountWindowKind,
    BillingComponent,
    Price,
    PriceSchedule,
)
from shared.model_access.effective_policy import EffectivePolicy

if TYPE_CHECKING:
    from engine.models import ModelAllocation, ModelBudgetAccount, ModelRequestReservation

# Bigint ceiling for money/counter columns; a charge that would exceed it is a
# misconfiguration and must reject rather than silently wrap.
_MAX_BIGINT = 9_223_372_036_854_775_807
# Spend accounts, price schedules and grant limits are all denominated in integer
# micro-units of one currency; a hold or settlement across a mismatched currency
# or unit is a fail-closed error, never a silent numeric coincidence.
_SPEND_UNIT = "micro_units"
LIFETIME_WINDOW_START = datetime(1970, 1, 1, tzinfo=UTC)
LIFETIME_WINDOW_END = datetime(9999, 12, 31, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# One posted account and the amount its dimension holds, carried from admission to
# posting: (account_ref, locked account row, held amount, dimension, pinned revision).
_AccountHold = tuple[str, "ModelBudgetAccount", int, AccountDimension, int]


@dataclass(frozen=True)
class RequestIdempotency:
    """Caller idempotency evidence for a request: HMAC digests only, never raw values.

    ``prior_caller_key_hmacs`` carries the same caller key hashed under every
    still-retained key version so an HMAC rotation cannot turn a retry into a
    second billable request.
    """

    caller_key_hmac: str | None = None
    prior_caller_key_hmacs: tuple[str, ...] = ()
    prior_intent_fingerprint_hmacs: tuple[str, ...] = ()
    retained_key_versions: tuple[str, ...] = ()
    key_version: str | None = None
    intent_fingerprint_hmac: str | None = None
    intent_contract_version: str | None = None


_NO_IDEMPOTENCY = RequestIdempotency()


@dataclass(frozen=True)
class ReservationOutcome:
    """The committed reservation identity and its canonical provider-cost figure."""

    request_uuid: UUID
    canonical_request_cost: int
    account_refs: tuple[str, ...] = field(default_factory=tuple)


def reserve_request(
    *,
    allocation_id: UUID,
    request_uuid: UUID,
    logical_alias: str,
    billing_bound: BillingBound,
    now: datetime | None = None,
    idempotency: RequestIdempotency | None = None,
    projection: AccountPolicyProjection | None = None,
) -> ReservationOutcome:
    """Reserve every applicable account atomically with a strict pre-dispatch audit."""
    from engine.models import ModelAllocation, ModelBudgetPosting, ModelRequestReservation

    idem = idempotency or _NO_IDEMPOTENCY
    moment = now or datetime.now(UTC)
    with transaction.atomic():
        allocation = _lock_allocation(allocation_id, moment)
        grant_epoch = _lock_grant_epoch(allocation)
        _recheck_authority(allocation)

        catalog, effective = _load_snapshot(allocation)
        if logical_alias not in allocation.alias_shards:
            raise ContractError("request.alias_unavailable")
        spend_currency, upper_charge = _conservative_charge(
            catalog, logical_alias, billing_bound, moment, effective, allocation.alias_shards[logical_alias]
        )

        existing = _replay(allocation, grant_epoch, idem)
        if existing is not None:
            return _outcome(existing)

        resolved = resolve_request_accounts(
            catalog=catalog,
            spend_account_refs=effective.spend_account_refs,
            rate_account_refs=effective.rate_account_refs,
            concurrency_account_refs=effective.concurrency_account_refs,
            projection=projection,
        )
        _assert_spend_currency(resolved, spend_currency)
        holds = _held_amounts(resolved, upper_charge)
        vector = _admit_accounts(allocation.deployment_id, holds, moment)

        reservation = ModelRequestReservation.objects.create(
            request_uuid=request_uuid,
            allocation=allocation,
            operation_id=allocation.operation_id,
            grant_epoch=grant_epoch,
            logical_alias=logical_alias,
            shard=allocation.snapshot["shards"][logical_alias],
            caller_key_hmac=idem.caller_key_hmac or "",
            key_version=idem.key_version or "",
            intent_fingerprint_hmac=idem.intent_fingerprint_hmac or "",
            intent_contract_version=idem.intent_contract_version or "",
            reservation_vector={ref: held for ref, _account, held, _dim, _rev in vector},
            billed_components=sorted({amount.component.value for amount in billing_bound.amounts}),
            canonical_request_cost=upper_charge,
            billing_bound=billing_bound.model_dump(mode="json"),
        )
        for _ref, account, held, dimension, revision in vector:
            ModelBudgetPosting.objects.create(
                reservation=reservation, account=account, held=held, definition_revision=revision
            )
            _apply_hold(account, dimension, held)

        ModelAllocation.objects.filter(pk=allocation.pk).update(
            unresolved_liabilities=allocation.unresolved_liabilities + 1
        )
        _decision_audit(reservation)
        return _outcome(reservation)


def _lock_allocation(allocation_id: UUID, moment: datetime) -> ModelAllocation:
    """Lock the allocation (range/generation) and reject a released or expired one."""
    from engine.models import ModelAllocation

    try:
        allocation = ModelAllocation.objects.select_for_update().get(pk=allocation_id)
    except ModelAllocation.DoesNotExist:
        raise ContractError("request.allocation_unavailable") from None
    if allocation.released_at is not None:
        raise ContractError("request.allocation_released")
    if allocation.deadline <= moment:
        raise ContractError("request.allocation_expired")
    return allocation


def _lock_grant_epoch(allocation: ModelAllocation) -> int:
    """Lock the grant and return its epoch; a non-usable pending grant is refused."""
    from engine.models import ModelPendingGrant

    try:
        grant = ModelPendingGrant.objects.select_for_update().get(allocation=allocation)
    except ModelPendingGrant.DoesNotExist:
        raise ContractError("request.grant_unavailable") from None
    if grant.state == "revoked":
        raise ContractError("request.revoked")
    if grant.state != "active":
        # A pending grant is an enrollment binding, not live authority; only an issued
        # (active) capability authorizes a request. M04 never performs that activation.
        raise ContractError("request.grant_inactive")
    return grant.grant_epoch


def _recheck_authority(allocation: ModelAllocation) -> None:
    """Fail closed when any pinned sharing-authority fence revision has advanced."""
    from engine.models import ModelAllocationAuthority

    # The already-locked grant is the request-side serialization point. Owner
    # mutations hold their authority fence and revoke this grant in the same
    # transaction. Locking that fence here would invert fence -> grant ordering
    # and deadlock. A committed revocation cannot pass the grant check; a pending
    # mutation serializes after this admission when our grant lock is released.
    pins = ModelAllocationAuthority.objects.filter(allocation=allocation).order_by("fence_id")
    for pin in pins.select_related("fence"):
        if pin.fence.authority_revision != pin.revision or pin.fence.state != "allowed":
            raise ContractError("request.authority_changed")


def _load_snapshot(allocation: ModelAllocation) -> tuple[ModelAccessCatalogV3, EffectivePolicy]:
    """Reconstruct the immutable v3 catalog and effective policy captured at launch."""
    catalog = validate_catalog(allocation.snapshot["catalog"])
    if not isinstance(catalog, ModelAccessCatalogV3):
        # Budget enforcement requires the v3 account-definition contract; an older
        # snapshot catalog cannot authorize a billed request.
        raise ContractError("request.account_contract_unavailable")
    effective = EffectivePolicy.model_validate(allocation.snapshot["effective_policy"])
    if not effective.admissible:
        raise ContractError("request.policy_unavailable")
    return catalog, effective


def _conservative_charge(
    catalog: ModelAccessCatalogV3,
    logical_alias: str,
    billing_bound: BillingBound,
    moment: datetime,
    effective: EffectivePolicy,
    shard_id: str,
) -> tuple[str, int]:
    """Sum ceil(units * price / denominator) from the immutable price snapshot.

    Returns the schedule currency alongside the integer micro-unit charge so the
    caller can prove every spend account shares that currency before any hold.
    """
    schedule = _priced_schedule(catalog, logical_alias, moment, shard_id)
    prices: dict[BillingComponent, Price] = {price.component: price for price in schedule.prices}
    total = _sum_billing_components(billing_bound, prices)
    _assert_within_grant_bound(total, schedule.currency.value, effective)
    return schedule.currency.value, total


def _priced_schedule(
    catalog: ModelAccessCatalogV3, logical_alias: str, moment: datetime, shard_id: str
) -> PriceSchedule:
    """Resolve the selected source's immutable, unexpired price snapshot."""
    schedule = catalog.price_for_alias(logical_alias, shard_id)
    if schedule.valid_until <= moment:
        raise ContractError("request.price_expired")
    return schedule


def _sum_billing_components(billing_bound: BillingBound, prices: dict[BillingComponent, Price]) -> int:
    """Sum the conservative charge for every bounded component in integer micro-units."""
    total = 0
    for amount in billing_bound.amounts:
        price = prices.get(amount.component)
        if price is None:
            raise ContractError("request.price_unavailable")
        total += _checked_ceil(amount.units, price.price_micro_units, price.unit_denominator)
        if total > _MAX_BIGINT:
            raise ContractError("request.charge_overflow")
    return total


def _assert_within_grant_bound(total: int, currency: str, effective: EffectivePolicy) -> None:
    """The grant's per-request ceiling and the price schedule must share a currency."""
    limits = effective.effective_profile.limits if effective.effective_profile else None
    if limits is None:
        return
    if limits.currency.value != currency:
        raise ContractError("request.currency_mismatch")
    if total > limits.max_spend_micro_units:
        raise ContractError("request.bound_exceeds_grant")


def _assert_spend_currency(resolved: ResolvedRequestAccounts, currency: str) -> None:
    """Every spend account must share the request's currency and canonical unit."""
    for definition in resolved.spend:
        account_currency = definition.currency.value if definition.currency else ""
        if account_currency != currency or definition.unit != _SPEND_UNIT:
            raise ContractError("request.currency_mismatch")


def _checked_ceil(units: int, price_micro_units: int, unit_denominator: int) -> int:
    """Integer ceiling of units * price / denominator with an overflow guard."""
    product = units * price_micro_units
    if product > _MAX_BIGINT:
        raise ContractError("request.charge_overflow")
    return (product + unit_denominator - 1) // unit_denominator


def _held_amounts(resolved: ResolvedRequestAccounts, upper_charge: int) -> list[tuple[AccountDefinition, int]]:
    """Pair each applicable account definition with the amount its dimension holds."""
    holds: list[tuple[AccountDefinition, int]] = []
    for definition in resolved.spend:
        holds.append((definition, upper_charge))
    for definition in resolved.rate:
        holds.append((definition, 1))
    for definition in resolved.concurrency:
        holds.append((definition, 1))
    return holds


def _admit_accounts(
    deployment_id: UUID,
    holds: list[tuple[AccountDefinition, int]],
    moment: datetime,
) -> list[_AccountHold]:
    """Lock each account/window in canonical order and enforce S + R + U <= B."""
    vector: list[_AccountHold] = []
    for definition, held in sorted(holds, key=lambda item: item[0].account_ref):
        window_start, window_end = _window(definition, moment)
        account = _lock_account(deployment_id, definition, window_start, window_end)
        committed = _committed(account, definition.dimension)
        if committed + held > account.limit:
            raise ContractError("request.budget_exceeded")
        vector.append((definition.account_ref, account, held, definition.dimension, account.definition_revision))
    return vector


def _window(definition: AccountDefinition, moment: datetime) -> tuple[datetime, datetime]:
    """Resolve the explicit UTC window this request accrues against."""
    if definition.window.kind is AccountWindowKind.LIFETIME:
        return LIFETIME_WINDOW_START, LIFETIME_WINDOW_END
    period = definition.window.period_seconds
    if period is None:
        # Validated non-None for a rolling window; this narrows the type and fails closed.
        raise ContractError("request.window_unsupported")
    elapsed = int((moment - _EPOCH).total_seconds())
    start_seconds = (elapsed // period) * period
    window_start = _EPOCH + timedelta(seconds=start_seconds)
    return window_start, window_start + timedelta(seconds=period)


def _lock_account(
    deployment_id: UUID,
    definition: AccountDefinition,
    window_start: datetime,
    window_end: datetime,
) -> ModelBudgetAccount:
    """Ensure the durable account/window identity exists, then lock it FOR UPDATE."""
    from engine.models import ModelBudgetAccount

    identity = {
        "deployment_id": deployment_id,
        "account_ref": definition.account_ref,
        "window_start": window_start,
        "window_end": window_end,
    }
    try:
        with transaction.atomic():
            ModelBudgetAccount.objects.get_or_create(
                defaults={
                    "dimension": definition.dimension.value,
                    "unit": definition.unit,
                    "currency": definition.currency.value if definition.currency else "",
                    "limit": definition.ceiling,
                    "definition_revision": definition.definition_revision,
                },
                **identity,
            )
    except IntegrityError:
        # A concurrent first use created it; the locking read below wins.
        pass
    account = ModelBudgetAccount.objects.select_for_update().get(**identity)
    account_currency = definition.currency.value if definition.currency else ""
    if (
        account.dimension != definition.dimension.value
        or account.unit != definition.unit
        or account.currency != account_currency
    ):
        # A reference reused with changed dimension, unit or currency is a different
        # account masquerading as the same one; reject rather than post to it.
        raise ContractError("request.account_semantics_changed")
    if definition.definition_revision > account.definition_revision:
        # Only a strictly newer revision may move the live ceiling; a stale or equal
        # snapshot never overwrites the operator-owned authoritative balance row.
        account.limit = definition.ceiling
        account.definition_revision = definition.definition_revision
        account.save(update_fields=["limit", "definition_revision"])
    return account


def _committed(account: ModelBudgetAccount, dimension: AccountDimension) -> int:
    """The already-committed value this dimension's admission test must respect."""
    if dimension is AccountDimension.SPEND:
        return account.spent + account.reserved
    if dimension is AccountDimension.RATE:
        return account.requests
    return account.active_leases


def _apply_hold(account: ModelBudgetAccount, dimension: AccountDimension, held: int) -> None:
    """Record the hold on the locked account row for this dimension."""
    if dimension is AccountDimension.SPEND:
        account.reserved += held
    elif dimension is AccountDimension.RATE:
        account.requests += held
    else:
        account.active_leases += held
    account.save(update_fields=["reserved", "requests", "active_leases"])


def _replay(
    allocation: ModelAllocation,
    grant_epoch: int,
    idempotency: RequestIdempotency,
) -> ModelRequestReservation | None:
    """Return the winning reservation for a repeated key, or raise on changed intent.

    After an HMAC key rotation the same raw idempotency key yields a new digest, so
    the caller supplies the current digest plus every retained prior-version digest;
    a match on any of them is the same request and must not re-invoke the provider.
    """
    from engine.models import ModelRequestReservation

    if not idempotency.caller_key_hmac:
        # No idempotency key means this is always a new invocation.
        return None
    versions = set(
        ModelRequestReservation.objects.filter(
            allocation=allocation,
            grant_epoch=grant_epoch,
            operation_id=allocation.operation_id,
        )
        .exclude(caller_key_hmac="")
        .values_list("key_version", flat=True)
    )
    if versions - {idempotency.key_version or "", *idempotency.retained_key_versions}:
        raise ContractError("request.retry_key_rotation_unavailable")
    candidates = [hmac for hmac in (idempotency.caller_key_hmac, *idempotency.prior_caller_key_hmacs) if hmac]
    existing = (
        ModelRequestReservation.objects.select_for_update()
        .filter(
            allocation=allocation,
            grant_epoch=grant_epoch,
            operation_id=allocation.operation_id,
            caller_key_hmac__in=candidates,
        )
        .first()
    )
    if existing is None:
        return None
    if existing.intent_fingerprint_hmac not in {
        idempotency.intent_fingerprint_hmac or "",
        *idempotency.prior_intent_fingerprint_hmacs,
    }:
        raise ContractError("request.intent_conflict")
    if existing.state != "settled":
        raise ContractError("request.in_progress_or_unknown")
    return existing


def _decision_audit(reservation: ModelRequestReservation) -> None:
    """Commit the strict body-free decision/accounting audit before any dispatch."""
    from shared.audit import AuditActorType, AuditEvent, audit_log
    from shared.audit.vocabulary import AuditAction, AuditEntityType

    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.MODEL_REQUEST.value,
            entity_id=reservation.pk,
            action=AuditAction.MODEL_REQUEST_RESERVE.value,
            actor_type=AuditActorType.SYSTEM,
            context=f"reserve cost={reservation.canonical_request_cost} accounts={len(reservation.reservation_vector)}",
            entity_ref=str(reservation.request_uuid),
        ),
        strict=True,
    )


def _outcome(reservation: ModelRequestReservation) -> ReservationOutcome:
    """Render the committed reservation as its service-boundary outcome."""
    return ReservationOutcome(
        request_uuid=reservation.request_uuid,
        canonical_request_cost=reservation.canonical_request_cost,
        account_refs=tuple(reservation.reservation_vector.keys()),
    )
