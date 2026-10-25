"""Explicit deployment-owned provider pools without changing v1 wire digests."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from shared.model_access.core_models import ClosedModel, Identifier, _require_unique
from shared.model_access.models import ModelAccessCatalog


class ProviderPool(ClosedModel):
    """An explicit set of permitted shard identities, not additional quota."""

    provider_pool_id: Identifier
    shard_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=256)]

    @field_validator("shard_ids")
    @classmethod
    def normalize_shards(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Order membership canonically and reject duplicate declarations."""
        _require_unique(values, "shard_ids")
        return tuple(sorted(values))


class ModelAccessCatalogV2(ModelAccessCatalog):
    """v2 adds a required, explicit provider-pool inventory; v1 remains readable."""

    # Pydantic version subclasses intentionally replace the wire discriminant;
    # mypy treats the disjoint Literal override as an incompatible assignment.
    contract_version: Literal["model-access-policy/v2"]  # type: ignore[assignment]
    provider_pools: Annotated[tuple[ProviderPool, ...], Field(max_length=128)]

    @field_validator("provider_pools")
    @classmethod
    def normalize_provider_pools(cls, values: tuple[ProviderPool, ...]) -> tuple[ProviderPool, ...]:
        """Make ordering immaterial to catalog identity."""
        _require_unique(tuple(pool.provider_pool_id for pool in values), "provider_pool_id")
        return tuple(sorted(values, key=lambda pool: pool.provider_pool_id))

    @model_validator(mode="after")
    def validate_provider_membership(self) -> Self:
        """Every pool member and every sharing reference resolves in this revision."""
        shards = {shard.shard_id for shard in self.shards}
        pools = {pool.provider_pool_id for pool in self.provider_pools}
        if any(not set(pool.shard_ids).issubset(shards) for pool in self.provider_pools):
            raise ValueError("provider pool references unknown shard")
        if any(
            pool.provider_pool_ref is not None and pool.provider_pool_ref not in pools for pool in self.sharing_pools
        ):
            raise ValueError("sharing pool references unknown provider pool")
        return self
