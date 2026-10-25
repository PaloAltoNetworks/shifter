"""Admission from explicit tenant application caps, never fabricated cloud quota."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from engine.models import ModelSourceRevision

from django.utils import timezone

from shared.model_access import ContractError, ModelAccessCatalog
from shared.model_access.catalog_v4 import ModelAccessCatalogV4
from shared.model_access.core_models import ModelShard, QuotaPool
from shared.model_access.messages import JsonObject
from shared.model_access.reservation import ModelQuotaObservation
from shared.model_access.sources import ModelSourceConfiguration


def launch_model_observations(catalog: ModelAccessCatalog) -> tuple[JsonObject, ...]:
    """Combine unchanged legacy readings with published source application caps.

    Tenant caps are deliberate local ceilings, not a provider-health probe or a
    promise of cloud quota. The allocator still locks real quota identities and
    deducts every outstanding commitment. Upstream failures never cause fallback.
    No network operation occurs inside the admission transaction.
    """
    from django.db.models import F

    from engine.models import ModelQuotaReading, ModelSourceRevision

    if not isinstance(catalog, ModelAccessCatalogV4):
        return tuple(
            ModelQuotaReading.objects.filter(catalog_digest=catalog.digest).values_list("observation", flat=True)
        )
    moment = timezone.now()
    base_digest = catalog.authority_catalog_digest
    legacy = {
        item.quota_pool_id: item
        for item in (
            ModelQuotaObservation.model_validate(value)
            for value in ModelQuotaReading.objects.filter(catalog_digest=base_digest).values_list(
                "observation", flat=True
            )
        )
    }
    shards = {shard.shard_id: shard for shard in catalog.shards}
    source_ids = {binding.source_id for binding in catalog.source_bindings if binding.source_id is not None}
    current = {
        row.source_id: row
        for row in ModelSourceRevision.objects.select_related("source")
        .filter(source_id__in=source_ids, source__enabled=True, state="ready", revision=F("source__revision"))
        .order_by("source_id", "revision")
        if row.revision == row.source.revision
    }
    caps = _source_caps(catalog, current, shards, moment)
    return _combine_observations(catalog, caps, legacy, moment)


def _source_observation(
    catalog: ModelAccessCatalog,
    pool: QuotaPool,
    sources: list[tuple[str, ModelSourceConfiguration]],
    incumbent: ModelQuotaObservation | None,
    moment: datetime,
) -> JsonObject:
    """Do not erase incumbent usage when a tenant source shares its quota."""
    limits = [pool.limit, *(config.tokens_per_minute for _, config in sources)]
    expiries = [moment + timedelta(minutes=5), *(config.price_valid_until for _, config in sources)]
    healthy = {shard_id for shard_id, _ in sources}
    usage = 0
    if incumbent is not None:
        if not incumbent.observed_at <= moment < incumbent.valid_until:
            raise ContractError("allocation.invalid_input")
        limits.append(incumbent.limit)
        expiries.append(incumbent.valid_until)
        usage = incumbent.usage
        healthy.update(incumbent.healthy_shard_ids)
    return ModelQuotaObservation(
        quota_pool_id=pool.quota_pool_id,
        catalog_digest=catalog.digest,
        source="application_cap",
        observed_at=moment,
        valid_until=min(expiries),
        limit=min(limits),
        usage=usage,
        healthy_shard_ids=tuple(sorted(healthy)),
    ).model_dump(mode="json")


def _source_caps(
    catalog: ModelAccessCatalogV4,
    current: dict[UUID, "ModelSourceRevision"],
    shards: dict[str, ModelShard],
    moment: datetime,
) -> dict[str, list[tuple[str, ModelSourceConfiguration]]]:
    """Validate immutable source bindings before deriving application quota caps."""
    caps: dict[str, list[tuple[str, ModelSourceConfiguration]]] = {}
    for binding in catalog.source_bindings:
        if binding.source_id is None:
            continue
        row = current.get(binding.source_id)
        if row is None or row.revision != binding.source_revision:
            raise ContractError("source.revision_conflict")
        config = ModelSourceConfiguration.model_validate(row.configuration)
        config.target(binding.source_id, binding.source_revision).model_copy(
            update={"shard_id": binding.shard_id}
        ).bind(shards[binding.shard_id])
        if config.price_valid_until <= moment:
            raise ContractError("allocation.price_unavailable")
        for pool_id in shards[binding.shard_id].quota_pool_ids:
            caps.setdefault(pool_id, []).append((binding.shard_id, config))
    return caps


def _combine_observations(
    catalog: ModelAccessCatalogV4,
    caps: dict[str, list[tuple[str, ModelSourceConfiguration]]],
    legacy: dict[str, ModelQuotaObservation],
    moment: datetime,
) -> tuple[JsonObject, ...]:
    """Preserve legacy usage and apply explicit source caps to every bound pool."""
    observations = []
    for pool in catalog.quota_pools:
        sources = caps.get(pool.quota_pool_id)
        if sources:
            observations.append(_source_observation(catalog, pool, sources, legacy.get(pool.quota_pool_id), moment))
        elif pool.quota_pool_id in legacy:
            observations.append(
                legacy[pool.quota_pool_id].model_copy(update={"catalog_digest": catalog.digest}).model_dump(mode="json")
            )
    return tuple(observations)
