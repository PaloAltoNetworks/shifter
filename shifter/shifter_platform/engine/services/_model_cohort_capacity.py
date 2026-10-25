"""Whole-event commitments apportioned across weighted independent sources."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from engine.models import AllocationGroup
from shared.model_access import ContractError, ModelAccessCatalog
from shared.model_access.core_models import AllocationStrategy, EffectiveProfile, ModelAlias, ModelShard
from shared.model_access.effective_policy import EffectivePolicy
from shared.model_access.reservation import ModelAllocationRequest, ModelQuotaObservation

from ._model_allocation_selection import _eligible, _provider_candidates
from ._model_quota import add_shard_demand


def cohort_commitments(
    request: ModelAllocationRequest,
    catalog: ModelAccessCatalog,
    sharing: EffectivePolicy,
    profile: EffectiveProfile,
    observations: dict[str, ModelQuotaObservation],
    groups: dict[str, AllocationGroup],
) -> dict[str, int] | None:
    """Reserve the entire cohort once, retaining each real quota constraint.

    Shared routing deliberately pins an affinity group to one source and keeps
    its incumbent whole-group reservation. Independent event routing can split
    participants across sources; largest-remainder apportionment gives exact
    integer slots without inventing fractional participants or extra capacity.
    """
    aliases = [alias for alias in catalog.aliases if alias.profile_id == request.need.profile_id]
    if not _mixes_independent_event(request, catalog, groups, aliases):
        return None
    context = _CohortCandidates(
        request, catalog, profile, observations, _provider_candidates(catalog, sharing), timezone.now()
    )
    commitments: defaultdict[str, int] = defaultdict(int)
    for alias in aliases:
        candidates = context.for_alias(alias)
        if not candidates:
            raise ContractError("allocation.capacity_unavailable")
        if alias.strategy == AllocationStrategy.FIXED_V1:
            candidates = candidates[:1]
        for pool_id, amount in _alias_commitments(candidates, catalog, request).items():
            commitments[pool_id] += amount
    return {pool_id: amount for pool_id, amount in commitments.items() if amount}


@dataclass(frozen=True)
class _CohortCandidates:
    """Admission inputs shared across each alias in a cohort."""

    request: ModelAllocationRequest
    catalog: ModelAccessCatalog
    profile: EffectiveProfile
    observations: dict[str, ModelQuotaObservation]
    allowed: set[str]
    moment: datetime

    def for_alias(self, alias: ModelAlias) -> list[ModelShard]:
        """Keep healthy, authorized candidates with prices covering the event window."""
        return [
            shard
            for shard in self.catalog.shards
            if shard.shard_id in alias.eligible_shard_ids
            and shard.shard_id in self.allowed
            and _eligible(shard, self.profile, self.observations, self.moment)
            and self._price_covers(alias.logical_alias, shard.shard_id)
        ]

    def _price_covers(self, alias: str, shard: str) -> bool:
        """Require matching currency and validity through the complete cohort window."""
        price = self.catalog.price_for_alias(alias, shard)
        return price.valid_until >= self.request.window_end and price.currency == self.profile.limits.currency


def _slots(shards: list[ModelShard], count: int) -> list[tuple[ModelShard, int]]:
    """Stable rounding with total slots exactly equal to event concurrency."""
    total_weight = sum(shard.weight for shard in shards)
    counts = {shard.shard_id: count * shard.weight // total_weight for shard in shards}
    remaining = count - sum(counts.values())
    ranked = sorted(shards, key=lambda shard: (-(count * shard.weight % total_weight), shard.shard_id))
    for shard in ranked[:remaining]:
        counts[shard.shard_id] += 1
    return [(shard, counts[shard.shard_id]) for shard in shards]


def _mixes_independent_event(
    request: ModelAllocationRequest,
    catalog: ModelAccessCatalog,
    groups: dict[str, AllocationGroup],
    aliases: list[ModelAlias],
) -> bool:
    """Only independent weighted event routing apportions whole-cohort capacity."""
    return (
        catalog.contract_version == "model-access-policy/v4"
        and request.scope_kind == "event"
        and not groups
        and any(alias.strategy == AllocationStrategy.WEIGHTED_RENDEZVOUS_V1 for alias in aliases)
    )


def _alias_commitments(
    shards: list[ModelShard], catalog: ModelAccessCatalog, request: ModelAllocationRequest
) -> dict[str, int]:
    """Sum integer participant slots against every shard's physical quota pools."""
    commitments: defaultdict[str, int] = defaultdict(int)
    for shard, slots in _slots(shards, request.demand.expected_concurrency):
        for pool_id, amount in add_shard_demand({}, shard, catalog, request.demand).items():
            commitments[pool_id] += amount * slots
    return dict(commitments)
