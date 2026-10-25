"""Pure shard ranking and provider eligibility for atomic model allocation."""

from datetime import datetime

from engine.models import AllocationGroup
from shared.model_access import ContractError, ModelAccessCatalog, compute_digest
from shared.model_access.allocation import ShardWeight, rank_weighted_rendezvous
from shared.model_access.core_models import AllocationStrategy, EffectiveProfile, ModelAlias, ModelShard
from shared.model_access.effective_policy import EffectivePolicy
from shared.model_access.reservation import ModelAllocationRequest, ModelQuotaObservation


def _rank(
    alias: ModelAlias,
    request: ModelAllocationRequest,
    catalog: ModelAccessCatalog,
    policy_digest: str,
    group: AllocationGroup | None = None,
) -> list[ModelShard]:
    """Rank eligible shards under the catalog's declared strategy."""
    if catalog.contract_version == "model-access-policy/v4":
        if alias.strategy not in request.need.allowed_strategies:
            raise ContractError("allocation.strategy_not_allowed")
    elif request.demand.allowed_strategy != alias.strategy:
        raise ContractError("allocation.strategy_not_allowed")
    candidates = [item for item in catalog.shards if item.shard_id in alias.eligible_shard_ids]
    if alias.strategy is AllocationStrategy.FIXED_V1:
        return candidates
    ranks = rank_weighted_rendezvous(
        deployment_id=catalog.deployment_id,
        allocation_group_id=group.allocation_group_id if group else request.draw_key,
        policy_digest=policy_digest,
        logical_alias=alias.logical_alias,
        shards=tuple(ShardWeight(item.shard_id, item.weight) for item in candidates),
    )
    by_id = {item.shard_id: item for item in candidates}
    return [by_id[item.shard_id] for item in ranks]


def _eligible(
    shard: ModelShard,
    profile: EffectiveProfile,
    observations: dict[str, ModelQuotaObservation],
    now: datetime,
) -> bool:
    """Check immutable shard policy plus fresh provider observations."""
    return (
        shard.enabled
        and shard.region in profile.data_regions
        and set(profile.capabilities).issubset(shard.capabilities)
        and all(
            pool_id in observations
            and observations[pool_id].observed_at <= now < observations[pool_id].valid_until
            and shard.shard_id in observations[pool_id].healthy_shard_ids
            for pool_id in shard.quota_pool_ids
        )
    )


def _provider_candidates(catalog: ModelAccessCatalog, sharing: EffectivePolicy) -> set[str]:
    """Intersect a declared provider pool; absent legacy mappings fail closed."""
    if sharing.provider_pool_ref is None:
        return {shard.shard_id for shard in catalog.shards}
    for pool in getattr(catalog, "provider_pools", ()):
        if pool.provider_pool_id == sharing.provider_pool_ref:
            return set(pool.shard_ids)
    raise ContractError("allocation.provider_pool_unavailable")


def _policy_digest(request: ModelAllocationRequest, catalog: ModelAccessCatalog, profile: EffectiveProfile) -> str:
    """Bind the routing decision to its exact catalog, need, and profile."""
    return compute_digest(
        {
            "catalog": catalog.digest,
            "profile": profile.model_dump(mode="json"),
            "need": request.need.model_dump(mode="json"),
        }
    )
