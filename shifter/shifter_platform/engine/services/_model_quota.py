"""Ordered real-quota locking and exact model reservation/draw effects."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Sum
from django.utils import timezone

from engine.models import (
    CapacityAssessment,
    ModelAllocation,
    ModelCapacityDraw,
    ModelCapacityReservation,
    ModelQuotaIdentity,
)
from shared.model_access import ContractError, ModelAccessCatalog, compute_digest
from shared.model_access.admission import EventModelDemand
from shared.model_access.core_models import ModelShard, QuotaPool
from shared.model_access.effective_policy import EffectivePolicy
from shared.model_access.reservation import ModelAllocationRequest, ModelQuotaObservation


def lock_quotas(
    catalog: ModelAccessCatalog,
    profile_id: str | None = None,
    allowed_shards: set[str] | None = None,
    retained_ids: set[str] | tuple[str, ...] = (),
) -> dict[str, ModelQuotaIdentity]:
    """Lock identities rather than possibly empty reservation queries."""
    identities: dict[str, tuple[str, dict[str, str] | None]] = {}
    candidates = {
        shard_id
        for alias in catalog.aliases
        if profile_id is None or alias.profile_id == profile_id
        for shard_id in alias.eligible_shard_ids
    }
    if allowed_shards is not None:
        candidates &= allowed_shards
    required = {pool_id for shard in catalog.shards if shard.shard_id in candidates for pool_id in shard.quota_pool_ids}
    for pool in catalog.quota_pools:
        if pool.quota_pool_id not in required:
            continue
        quota_fields = {
            "deployment_id": str(catalog.deployment_id),
            "provider_adapter_id": pool.provider_adapter_id,
            "provider_quota_identity": pool.provider_quota_identity,
            "dimension": pool.dimension,
            "unit": pool.unit,
        }
        identities[pool.quota_pool_id] = (compute_digest(quota_fields), quota_fields)
    locked = {}
    identities.update({f"retained:{identity}": (identity, None) for identity in retained_ids})
    for name, (identity, identity_fields) in sorted(identities.items(), key=lambda item: item[1][0]):
        if identity_fields is not None:
            ModelQuotaIdentity.objects.get_or_create(identity=identity, defaults=identity_fields)
        locked[name] = ModelQuotaIdentity.objects.select_for_update().get(identity=identity)
    return locked


def metric_amount(pool: QuotaPool, demand: EventModelDemand) -> int:
    """Map only supported exact dimensions and units; unknown means no admission."""
    values = {
        ("requests", "requests/minute"): demand.per_participant_requests,
        ("input_tokens", "tokens/minute"): demand.per_participant_input_tokens,
        ("output_tokens", "tokens/minute"): demand.per_participant_output_tokens,
        ("concurrency", "requests"): 1,
    }
    value = values.get((pool.dimension, pool.unit))
    if value is None or not 0 < value <= 2**63 - 1:
        raise ContractError("allocation.unsupported_metric")
    return value


def capacity_scope(request: ModelAllocationRequest, effective: EffectivePolicy) -> tuple[str, ...]:
    """Overlapping selectors coalesce at the stable capacity-account identity."""
    if effective.capacity_account_refs:
        return tuple(f"shared:{ref}" for ref in sorted(set(effective.capacity_account_refs)))
    # A replacement has a distinct dedicated commitment. A released original
    # remains a tombstone; it must never be revived for the successor.
    generation = f":{request.operation_id}" if request.scope_kind in {"standalone", "warm"} else ""
    policy = (
        f":policy:{request.source_policy_revision}"
        if request.source_policy_revision and request.scope_kind in {"standalone", "warm"}
        else ""
    )
    return (f"{request.scope_kind}:{request.scope_id}{generation}{policy}",)


def _parent(quota: ModelQuotaIdentity, scope: str, request: ModelAllocationRequest) -> ModelCapacityReservation | None:
    """Find the exact parent commitment for a capacity scope and window."""
    return ModelCapacityReservation.objects.filter(
        quota=quota,
        scope_key=scope,
        window_start=request.window_start,
        window_end=request.window_end,
    ).first()


def _observed_headroom(
    pool: QuotaPool,
    observation: ModelQuotaObservation | None,
    catalog_digest: str,
    now: datetime,
) -> int | None:
    """Return fresh usable headroom or deny an absent/stale observation."""
    if observation is None or observation.catalog_digest != catalog_digest:
        return None
    if not observation.observed_at <= now < observation.valid_until:
        return None
    return min(pool.limit, observation.limit) - observation.usage


def _additional_commitment(
    *,
    quota: ModelQuotaIdentity,
    scopes: tuple[str, ...],
    request: ModelAllocationRequest,
    amount: int,
    commitment: int,
    exact: bool,
) -> int | None:
    """Compute new parent capacity, or deny a released/exhausted parent."""
    added = 0
    for scope in scopes:
        parent = _parent(quota, scope, request)
        if parent is None:
            added += commitment
            continue
        budget = parent.workload_budgets.get(request.need.workload_role)
        if parent.released_at is not None:
            return None
        if budget is None:
            added += commitment
        elif budget["consumed"] + amount > (min(budget["amount"], commitment) if exact else budget["amount"]) or (
            exact and budget["amount"] < commitment
        ):
            return None
    return added


@dataclass(frozen=True)
class _FitContext:
    """Locked inputs shared by every physical-pool feasibility check."""

    request: ModelAllocationRequest
    catalog: ModelAccessCatalog
    locked: dict[str, ModelQuotaIdentity]
    observations: dict[str, ModelQuotaObservation]
    scopes: tuple[str, ...]
    factor: int
    commitments: dict[str, int] | None
    now: datetime


def _pool_fits(pool_id: str, amount: int, context: _FitContext) -> bool:
    """Check one physical quota after its durable mutex is held."""
    pools = {pool.quota_pool_id: pool for pool in context.catalog.quota_pools}
    headroom = _observed_headroom(
        pools[pool_id], context.observations.get(pool_id), context.catalog.digest, context.now
    )
    if headroom is None:
        return False
    quota = context.locked[pool_id]
    added = _additional_commitment(
        quota=quota,
        scopes=context.scopes,
        request=context.request,
        amount=amount,
        commitment=context.commitments[pool_id] if context.commitments is not None else amount * context.factor,
        exact=context.commitments is not None,
    )
    if added is None:
        return False
    committed = (
        ModelCapacityReservation.objects.filter(
            quota=quota,
            released_at__isnull=True,
            window_start__lt=context.request.window_end,
            window_end__gt=context.request.window_start,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return added <= 2**63 - 1 and committed + added <= headroom


def vector_fits(
    vector: dict[str, int],
    *,
    request: ModelAllocationRequest,
    effective: EffectivePolicy,
    catalog: ModelAccessCatalog,
    locked: dict[str, ModelQuotaIdentity],
    observations: dict[str, ModelQuotaObservation],
    commitments: dict[str, int] | None = None,
) -> bool:
    """Recheck freshness after waiting for locks, then every parent and real pool."""
    now = timezone.now()
    if now >= request.window_end:
        raise ContractError("allocation.expired")
    scopes = capacity_scope(request, effective)
    factor = (
        1
        if request.scope_kind == "standalone" and not effective.capacity_account_refs
        else request.demand.expected_concurrency
    )
    context = _FitContext(
        request=request,
        catalog=catalog,
        locked=locked,
        observations=observations,
        scopes=scopes,
        factor=factor,
        commitments=commitments,
        now=now,
    )
    if commitments is not None and any(amount > commitments.get(pool_id, 0) for pool_id, amount in vector.items()):
        return False
    return all(
        _pool_fits(pool_id, vector.get(pool_id, 0), context)
        for pool_id in (commitments if commitments is not None else vector)
    )


def add_shard_demand(
    vector: dict[str, int],
    shard: ModelShard,
    catalog: ModelAccessCatalog,
    demand: EventModelDemand,
) -> dict[str, int]:
    """Distinct alias demands sum once on each physical metric."""
    updated = defaultdict(int, vector)
    pools = {pool.quota_pool_id: pool for pool in catalog.quota_pools}
    for pool_id in shard.quota_pool_ids:
        updated[pool_id] += metric_amount(pools[pool_id], demand)
    return dict(updated)


@dataclass(frozen=True)
class QuotaAdmissionState:
    """Locked physical quota identities and their validated observations."""

    locked: dict[str, ModelQuotaIdentity]
    observations: dict[str, ModelQuotaObservation]


def persist_draws(
    allocation: ModelAllocation,
    vector: dict[str, int],
    *,
    request: ModelAllocationRequest,
    effective: EffectivePolicy,
    catalog: ModelAccessCatalog,
    quota: QuotaAdmissionState,
    commitments: dict[str, int] | None = None,
) -> None:
    """Write the whole effect vector in the allocation caller's transaction."""
    locked, observations = quota.locked, quota.observations
    scopes = capacity_scope(request, effective)
    factor = (
        1
        if request.scope_kind == "standalone" and not effective.capacity_account_refs
        else request.demand.expected_concurrency
    )
    planned = commitments if commitments is not None else {key: amount * factor for key, amount in vector.items()}
    assessment = CapacityAssessment.objects.create(
        # ADR-047's opaque upstream scope reference also accepts an explicitly
        # typed non-event UUID. The typed scope is retained on each commitment.
        event_ref=request.scope_id,
        partition_name="model-access",
        policy_version=catalog.digest.removeprefix("sha256:"),
        outcome="admitted",
        observed_at=min(observations[key].observed_at for key in planned),
        verdicts=[
            {"metric": key, "outcome": "admitted", "reason_code": "available", "enforcement": "enforcing"}
            for key in sorted(planned)
        ],
    )
    for pool_id, commitment in sorted(planned.items(), key=lambda item: locked[item[0]].pk):
        amount = vector.get(pool_id, 0)
        for scope in scopes:
            parent = _parent(locked[pool_id], scope, request)
            if parent is None:
                parent = ModelCapacityReservation.objects.create(
                    quota=locked[pool_id],
                    assessment=assessment,
                    scope_key=scope,
                    window_start=request.window_start,
                    window_end=request.window_end,
                    amount=commitment,
                    observation=observations[pool_id].model_dump(mode="json"),
                    workload_budgets={request.need.workload_role: {"amount": commitment, "consumed": 0}},
                )
            elif request.need.workload_role not in parent.workload_budgets:
                parent.amount += commitment
                parent.workload_budgets[request.need.workload_role] = {"amount": commitment, "consumed": 0}
            parent.workload_budgets[request.need.workload_role]["consumed"] += amount
            parent.consumed += amount
            parent.save(update_fields=["amount", "consumed", "workload_budgets"])
            if amount:
                ModelCapacityDraw.objects.create(allocation=allocation, reservation=parent, amount=amount)
