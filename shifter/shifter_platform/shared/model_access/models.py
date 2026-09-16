"""Aggregate model-access catalog and grant DTOs (PLAT-202)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, field_validator, model_validator

from shared.model_access.core_models import (
    AccessLimits,
    BillingComponent,
    ClosedModel,
    Digest,
    Identifier,
    ModelAlias,
    ModelProfile,
    ModelShard,
    OwnedReference,
    PositiveInt,
    PriceSchedule,
    QuotaPool,
    _require_unique,
)
from shared.model_access.sharing_models import SharingBinding, SharingPool


class ModelAccessCatalog(ClosedModel):
    """Type for ModelAccessCatalog."""

    contract_version: Literal["model-access-policy/v1"]
    deployment_id: UUID
    enabled: StrictBool
    profiles: Annotated[tuple[ModelProfile, ...], Field(min_length=1, max_length=64)]
    quota_pools: Annotated[tuple[QuotaPool, ...], Field(min_length=1, max_length=256)]
    price_schedules: Annotated[tuple[PriceSchedule, ...], Field(min_length=1, max_length=128)]
    shards: Annotated[tuple[ModelShard, ...], Field(min_length=1, max_length=256)]
    aliases: Annotated[tuple[ModelAlias, ...], Field(min_length=1, max_length=128)]
    sharing_pools: Annotated[tuple[SharingPool, ...], Field(max_length=128)] = ()
    sharing_bindings: Annotated[tuple[SharingBinding, ...], Field(max_length=256)] = ()
    digest: Digest

    @field_validator("profiles")
    @classmethod
    def _normalize_profiles(cls, values: tuple[ModelProfile, ...]) -> tuple[ModelProfile, ...]:
        """Operation for normalize profiles."""
        return tuple(sorted(values, key=lambda item: item.profile_id))

    @field_validator("quota_pools")
    @classmethod
    def _normalize_quota_pools(cls, values: tuple[QuotaPool, ...]) -> tuple[QuotaPool, ...]:
        """Operation for normalize quota pools."""
        return tuple(sorted(values, key=lambda item: item.quota_pool_id))

    @field_validator("price_schedules")
    @classmethod
    def _normalize_prices(cls, values: tuple[PriceSchedule, ...]) -> tuple[PriceSchedule, ...]:
        """Operation for normalize prices."""
        return tuple(sorted(values, key=lambda item: item.price_schedule_id))

    @field_validator("shards")
    @classmethod
    def _normalize_shards(cls, values: tuple[ModelShard, ...]) -> tuple[ModelShard, ...]:
        """Operation for normalize shards."""
        return tuple(sorted(values, key=lambda item: item.shard_id))

    @field_validator("aliases")
    @classmethod
    def _normalize_aliases(cls, values: tuple[ModelAlias, ...]) -> tuple[ModelAlias, ...]:
        """Operation for normalize aliases."""
        return tuple(sorted(values, key=lambda item: item.logical_alias))

    @field_validator("sharing_pools")
    @classmethod
    def _normalize_sharing_pools(cls, values: tuple[SharingPool, ...]) -> tuple[SharingPool, ...]:
        """Operation for normalize sharing pools."""
        return tuple(sorted(values, key=lambda item: item.sharing_pool_id))

    @field_validator("sharing_bindings")
    @classmethod
    def _normalize_bindings(cls, values: tuple[SharingBinding, ...]) -> tuple[SharingBinding, ...]:
        """Operation for normalize bindings."""
        return tuple(sorted(values, key=lambda item: item.sharing_binding_id))

    @model_validator(mode="after")
    def _validate_references(self) -> ModelAccessCatalog:
        """Operation for validate references."""
        ids = _catalog_ids(self)
        _validate_quota_references(self, ids)
        _validate_alias_references(self, ids)
        _validate_sharing_references(self, ids)
        return self


def _catalog_ids(catalog: ModelAccessCatalog) -> dict[str, set[str]]:
    """Operation for catalog ids."""
    collections = {
        "profiles": (catalog.profiles, "profile_id"),
        "quota_pools": (catalog.quota_pools, "quota_pool_id"),
        "price_schedules": (catalog.price_schedules, "price_schedule_id"),
        "shards": (catalog.shards, "shard_id"),
        "aliases": (catalog.aliases, "logical_alias"),
        "sharing_pools": (catalog.sharing_pools, "sharing_pool_id"),
        "sharing_bindings": (catalog.sharing_bindings, "sharing_binding_id"),
    }
    ids: dict[str, set[str]] = {}
    for name, (items, field_name) in collections.items():
        values = tuple(str(getattr(item, field_name)) for item in items)
        _require_unique(values, field_name)
        ids[name] = set(values)
    return ids


def _validate_quota_references(catalog: ModelAccessCatalog, ids: dict[str, set[str]]) -> None:
    """Operation for validate quota references."""
    real_quotas = tuple(
        (pool.provider_adapter_id, pool.provider_quota_identity, pool.dimension, pool.unit)
        for pool in catalog.quota_pools
    )
    if len(real_quotas) != len(set(real_quotas)):
        raise ValueError("one real provider quota identity must map to one quota pool")
    pools = {pool.quota_pool_id: pool for pool in catalog.quota_pools}
    for shard in catalog.shards:
        if not set(shard.quota_pool_ids).issubset(ids["quota_pools"]):
            raise ValueError("shard references an unknown quota pool")
        if any(pools[pool_id].provider_adapter_id != shard.provider_adapter_id for pool_id in shard.quota_pool_ids):
            raise ValueError("shard and quota pool adapter identities differ")


def _validate_alias_references(catalog: ModelAccessCatalog, ids: dict[str, set[str]]) -> None:
    """Operation for validate alias references."""
    shards = {item.shard_id: item for item in catalog.shards}
    prices = {item.price_schedule_id: item for item in catalog.price_schedules}
    profiles = {item.profile_id: item for item in catalog.profiles}
    for alias in catalog.aliases:
        _validate_alias(alias, ids, shards, prices, profiles)


def _validate_alias(
    alias: ModelAlias,
    ids: dict[str, set[str]],
    shards: dict[str, ModelShard],
    prices: dict[str, PriceSchedule],
    profiles: dict[str, ModelProfile],
) -> None:
    """Operation for validate alias."""
    if alias.profile_id not in profiles or alias.price_schedule_id not in prices:
        raise ValueError("alias references an unknown profile or price schedule")
    if not set(alias.eligible_shard_ids).issubset(ids["shards"]):
        raise ValueError("alias references an unknown shard")
    profile = profiles[alias.profile_id]
    if alias.strategy not in profile.allowed_strategies:
        raise ValueError("alias strategy is not allowed by its profile")
    priced_components = {item.component for item in prices[alias.price_schedule_id].prices}
    for shard_id in alias.eligible_shard_ids:
        _validate_eligible_shard(shards[shard_id], profile, priced_components)


def _validate_eligible_shard(
    shard: ModelShard,
    profile: ModelProfile,
    priced_components: set[BillingComponent],
) -> None:
    """Operation for validate eligible shard."""
    if not set(profile.capabilities).issubset(shard.capabilities):
        raise ValueError("eligible shard cannot satisfy its profile")
    if not set(shard.billing_components).issubset(priced_components):
        raise ValueError("eligible shard has an unpriced billing component")
    if shard.region not in profile.data_regions:
        raise ValueError("eligible shard violates profile data regions")


def _validate_sharing_references(catalog: ModelAccessCatalog, ids: dict[str, set[str]]) -> None:
    """Operation for validate sharing references."""
    for pool in catalog.sharing_pools:
        if any(item.logical_alias not in ids["aliases"] for item in pool.alias_affinities):
            raise ValueError("sharing pool references an unknown alias")
    for binding in catalog.sharing_bindings:
        if binding.deployment_id != catalog.deployment_id or binding.sharing_pool_id not in ids["sharing_pools"]:
            raise ValueError("sharing binding references another deployment or unknown pool")
        if binding.profile_id is not None and binding.profile_id not in ids["profiles"]:
            raise ValueError("sharing binding references an unknown profile")


class AccessGrant(ClosedModel):
    """Type for AccessGrant."""

    contract_version: Literal["model-access-grant/v1"]
    deployment_id: UUID
    range_id: UUID
    execution_generation_id: UUID
    subject_ref: OwnedReference
    policy_digest: Digest
    grant_epoch: PositiveInt
    limits: AccessLimits
    deadline: datetime
    alias_shards: Annotated[dict[Identifier, Identifier], Field(max_length=128)]

    @field_validator("deadline")
    @classmethod
    def _deadline_has_timezone(cls, value: datetime) -> datetime:
        """Operation for deadline has timezone."""
        if value.tzinfo is None:
            raise ValueError("deadline must include a timezone")
        return value
