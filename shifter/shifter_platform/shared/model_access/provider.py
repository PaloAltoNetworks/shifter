"""Closed provider adapter protocol and safe result vocabulary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from shared.model_access.catalog import ContractError
from shared.model_access.core_models import (
    BillingComponent,
    Capability,
    ClosedModel,
    Identifier,
    ModelShard,
    PositiveInt,
)

_CAPABILITY_MISMATCH = "provider.capability_mismatch"


class ProviderErrorCategory(StrEnum):
    """Type for ProviderErrorCategory."""

    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    DEADLINE = "deadline"
    UNKNOWN = "unknown"


class CancellationDisposition(StrEnum):
    """Type for CancellationDisposition."""

    CONFIRMED = "confirmed"
    REQUESTED_UNCONFIRMED = "requested_unconfirmed"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProviderCapabilities(ClosedModel):
    """Type for ProviderCapabilities."""

    adapter_id: Identifier
    protocols: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...],
        Field(min_length=1, max_length=32),
    ]
    models: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(min_length=1, max_length=256),
    ]
    capabilities: Annotated[tuple[Capability, ...], Field(max_length=64)]
    billing_components: Annotated[tuple[BillingComponent, ...], Field(min_length=1, max_length=16)]
    trustworthy_usage_components: Annotated[tuple[BillingComponent, ...], Field(max_length=16)]
    streaming: StrictBool
    token_counting: StrictBool
    cancellation: StrictBool
    completion_horizon_seconds: PositiveInt

    @field_validator(
        "protocols",
        "models",
        "capabilities",
        "billing_components",
        "trustworthy_usage_components",
    )
    @classmethod
    def _normalize_sets(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """Operation for normalize sets."""
        rendered = tuple(sorted(values, key=str))
        if len(rendered) != len(set(rendered)):
            raise ValueError("provider capability sets must be unique")
        return rendered

    @model_validator(mode="after")
    def _usage_is_supported(self) -> ProviderCapabilities:
        """Operation for usage is supported."""
        if not set(self.trustworthy_usage_components).issubset(self.billing_components):
            raise ValueError("trustworthy usage must be a supported billing component")
        return self


class BillingAmount(ClosedModel):
    """Type for BillingAmount."""

    component: BillingComponent
    units: PositiveInt
    maximum_charge_micro_units: StrictInt = Field(ge=0)


class BillingBound(ClosedModel):
    """Type for BillingBound."""

    amounts: tuple[BillingAmount, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def _unique_components(self) -> BillingBound:
        """Operation for unique components."""
        if len({item.component for item in self.amounts}) != len(self.amounts):
            raise ValueError("billing bound components must be unique")
        return self


class VerifiedUsage(ClosedModel):
    """Type for VerifiedUsage."""

    component: BillingComponent
    units: StrictInt = Field(ge=0)
    provider_verified: StrictBool


class ProviderUsage(ClosedModel):
    """Type for ProviderUsage."""

    items: tuple[VerifiedUsage, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def _unique_components(self) -> ProviderUsage:
        """Operation for unique components."""
        if len({item.component for item in self.items}) != len(self.items):
            raise ValueError("usage components must be unique")
        return self


class ProviderError(ClosedModel):
    """Type for ProviderError."""

    category: ProviderErrorCategory
    retryable: StrictBool
    retry_after_seconds: StrictInt | None = Field(default=None, ge=0, le=3600)


class CancellationResult(ClosedModel):
    """Type for CancellationResult."""

    disposition: CancellationDisposition

    @property
    def may_release_reservation(self) -> bool:
        """Operation for may release reservation."""
        return self.disposition is CancellationDisposition.CONFIRMED


@runtime_checkable
class ModelProviderAdapter(Protocol):
    """Type for ModelProviderAdapter."""

    def capabilities(self) -> ProviderCapabilities: ...

    def billing_bound(self, *, model: str, features: tuple[str, ...], request_bytes: int) -> BillingBound: ...

    def normalize_usage(self, provider_result: object) -> ProviderUsage: ...

    def cancel(self, provider_request_id: str) -> CancellationResult: ...


AdapterFactory = Callable[[ModelShard], ModelProviderAdapter]


class ProviderAdapterRegistry:
    """Explicit model-provider registry independent of deployment compute cloud."""

    def __init__(self, factories: Mapping[str, AdapterFactory]) -> None:
        """Operation for init."""
        self._factories = dict(factories)
        if any(not key for key in self._factories):
            raise ValueError("adapter ids must be non-empty")

    def build(self, shard: ModelShard) -> ModelProviderAdapter:
        """Operation for build."""
        factory = self._factories.get(shard.provider_adapter_id)
        if factory is None:
            raise ContractError("provider.unknown_adapter", "provider_adapter_id")
        adapter = factory(shard)
        capabilities = adapter.capabilities()
        if capabilities.adapter_id != shard.provider_adapter_id:
            raise ContractError(_CAPABILITY_MISMATCH, "provider_adapter_id")
        if shard.protocol not in capabilities.protocols or shard.provider_model not in capabilities.models:
            raise ContractError(_CAPABILITY_MISMATCH)
        if not set(shard.capabilities).issubset(capabilities.capabilities):
            raise ContractError(_CAPABILITY_MISMATCH, "capabilities")
        if not set(shard.billing_components).issubset(capabilities.billing_components):
            raise ContractError(_CAPABILITY_MISMATCH, "billing_components")
        return adapter
