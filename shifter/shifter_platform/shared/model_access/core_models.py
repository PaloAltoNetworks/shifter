"""Core immutable model-access policy DTOs (PLAT-202).

These models are the semantic contract shared by configuration, Engine, the
broker, and provider adapters.  They intentionally contain references rather
than credentials and remain independent of Django and provider SDKs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")]
Capability = Annotated[str, Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")]
Region = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SelectorIdentity = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9:/._@-]*$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class ClosedModel(BaseModel):
    """Frozen DTO base with an exact, non-extensible member set."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AllocationStrategy(StrEnum):
    """Type for AllocationStrategy."""

    FIXED_V1 = "fixed-v1"
    WEIGHTED_RENDEZVOUS_V1 = "weighted-rendezvous-v1"


class AssignmentAffinity(StrEnum):
    """Type for AssignmentAffinity."""

    PER_RANGE = "per_range"
    PER_USER = "per_user"
    PER_POOL = "per_pool"


class Currency(StrEnum):
    """Type for Currency."""

    AUD = "AUD"
    CAD = "CAD"
    CHF = "CHF"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    USD = "USD"


class BillingComponent(StrEnum):
    """Type for BillingComponent."""

    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    CACHED_INPUT_TOKENS = "cached_input_tokens"
    CACHE_WRITE_TOKENS = "cache_write_tokens"
    REQUEST = "request"
    TOOL_CALL = "tool_call"
    IMAGE = "image"


class SelectorKind(StrEnum):
    """Type for SelectorKind."""

    SELECTED_RANGES = "selected_ranges"
    CTF_EVENT = "ctf_event"
    CTF_COHORT = "ctf_cohort"
    CTF_TEAM = "ctf_team"
    USER = "user"
    AUTH_GROUP = "auth_group"
    WORKSPACE = "workspace"
    ORGANIZATION = "organization"
    NAMED_COLLECTION = "named_collection"
    ALL_RANGES = "all_ranges"


class MembershipMode(StrEnum):
    """Type for MembershipMode."""

    SNAPSHOT = "snapshot"
    DYNAMIC = "dynamic"


class SharingFacet(StrEnum):
    """Type for SharingFacet."""

    PROFILE = "profile"
    PROVIDER_IDENTITY = "provider_identity"
    ROUTING = "routing"
    CAPACITY = "capacity"
    SPEND = "spend"
    RATE = "rate"
    CONCURRENCY = "concurrency"


def _require_unique(values: tuple[str | StrEnum, ...], field_name: str) -> None:
    """Operation for require unique."""
    rendered = [str(item) for item in values]
    if len(rendered) != len(set(rendered)):
        raise ValueError(f"{field_name} must not contain duplicate identities")


class AccessLimits(ClosedModel):
    """Finite request and deployment ceilings; omission never means unlimited."""

    max_request_seconds: PositiveInt
    max_request_bytes: PositiveInt
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_requests_per_window: PositiveInt
    request_window_seconds: PositiveInt
    max_spend_micro_units: PositiveInt
    currency: Currency
    max_concurrent_requests: PositiveInt

    def tightened_with(self, other: AccessLimits) -> AccessLimits:
        """Operation for tightened with."""
        if self.currency is not other.currency:
            raise ValueError("limits use different currencies")
        data = {
            name: min(getattr(self, name), getattr(other, name))
            for name in type(self).model_fields
            if name != "currency"
        }
        return AccessLimits(currency=self.currency, **data)


class OwnedReference(ClosedModel):
    """A typed owner-qualified reference, never embedded credential material."""

    owner: Identifier
    reference: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9:/._@-]*$")]


class ComputeTargetReference(OwnedReference):
    """Range compute-placement identity, independent of model routing."""


class ModelProjectReference(OwnedReference):
    """Provider project that serves the model."""


class ModelAccountReference(OwnedReference):
    """Provider billing/account identity for model usage."""


class DynamicSecretProjectReference(OwnedReference):
    """Project that owns dynamic secret storage, never a model project alias."""


class BrokerWorkloadIdentityReference(OwnedReference):
    """Broker workload principal allowed to obtain provider invocation identity."""


class ProviderCredentialReference(OwnedReference):
    """Opaque broker-owned credential reference without credential material."""


class ModelProfile(ClosedModel):
    """Type for ModelProfile."""

    profile_id: Identifier
    capabilities: Annotated[tuple[Capability, ...], Field(min_length=1, max_length=64)]
    allowed_strategies: Annotated[tuple[AllocationStrategy, ...], Field(min_length=1, max_length=2)]
    data_regions: Annotated[tuple[Region, ...], Field(min_length=1, max_length=32)]
    limits: AccessLimits

    @field_validator("capabilities", "allowed_strategies", "data_regions")
    @classmethod
    def _normalize_sets(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """Operation for normalize sets."""
        return tuple(sorted(values, key=str))

    @model_validator(mode="after")
    def _sets_are_unique(self) -> ModelProfile:
        """Operation for sets are unique."""
        _require_unique(self.capabilities, "capabilities")
        _require_unique(self.allowed_strategies, "allowed_strategies")
        _require_unique(self.data_regions, "data_regions")
        if "global" in self.data_regions:
            raise ValueError("global is not an explicit data region")
        return self


class ScenarioNeed(ClosedModel):
    """Type for ScenarioNeed."""

    contract_version: Literal["model-access-scenario/v1"]
    scenario_digest: Digest
    workload_role: Identifier
    profile_id: Identifier
    required: StrictBool
    required_capabilities: Annotated[tuple[Capability, ...], Field(max_length=64)]
    allowed_capabilities: Annotated[tuple[Capability, ...], Field(min_length=1, max_length=64)]
    allowed_strategies: Annotated[tuple[AllocationStrategy, ...], Field(min_length=1, max_length=2)]
    data_regions: Annotated[tuple[Region, ...], Field(min_length=1, max_length=32)]
    limits: AccessLimits

    @field_validator(
        "required_capabilities",
        "allowed_capabilities",
        "allowed_strategies",
        "data_regions",
    )
    @classmethod
    def _normalize_sets(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """Operation for normalize sets."""
        return tuple(sorted(values, key=str))

    @model_validator(mode="after")
    def _validate_need(self) -> ScenarioNeed:
        """Operation for validate need."""
        for field_name in (
            "required_capabilities",
            "allowed_capabilities",
            "allowed_strategies",
            "data_regions",
        ):
            _require_unique(getattr(self, field_name), field_name)
        if not set(self.required_capabilities).issubset(self.allowed_capabilities):
            raise ValueError("required capabilities must be allowed")
        return self


class EffectiveProfile(ClosedModel):
    """Type for EffectiveProfile."""

    profile_id: Identifier
    required: StrictBool
    capabilities: tuple[Capability, ...]
    allowed_strategies: tuple[AllocationStrategy, ...]
    data_regions: tuple[Region, ...]
    limits: AccessLimits


class QuotaPool(ClosedModel):
    """Type for QuotaPool."""

    quota_pool_id: Identifier
    provider_adapter_id: Identifier
    provider_quota_identity: Annotated[str, Field(min_length=1, max_length=256)]
    dimension: Identifier
    unit: Annotated[str, Field(min_length=1, max_length=64)]
    limit: PositiveInt


class Price(ClosedModel):
    """Type for Price."""

    component: BillingComponent
    unit_denominator: PositiveInt
    price_micro_units: NonNegativeInt


class PriceSchedule(ClosedModel):
    """Type for PriceSchedule."""

    price_schedule_id: Identifier
    currency: Currency
    valid_until: datetime
    prices: Annotated[tuple[Price, ...], Field(min_length=1, max_length=16)]

    @field_validator("prices")
    @classmethod
    def _normalize_prices(cls, values: tuple[Price, ...]) -> tuple[Price, ...]:
        """Operation for normalize prices."""
        return tuple(sorted(values, key=lambda item: item.component.value))

    @model_validator(mode="after")
    def _unique_components(self) -> PriceSchedule:
        """Operation for unique components."""
        _require_unique(tuple(price.component for price in self.prices), "prices.component")
        if self.valid_until.tzinfo is None:
            raise ValueError("valid_until must include a timezone")
        return self


class ModelShard(ClosedModel):
    """Type for ModelShard."""

    shard_id: Identifier
    provider_adapter_id: Identifier
    compute_target_ref: ComputeTargetReference
    model_project_ref: ModelProjectReference
    model_account_ref: ModelAccountReference
    dynamic_secret_project_ref: DynamicSecretProjectReference
    broker_workload_identity_ref: BrokerWorkloadIdentityReference
    credential_ref: ProviderCredentialReference
    region: Region
    provider_model: Annotated[str, Field(min_length=1, max_length=256)]
    provider_model_version: Annotated[str, Field(min_length=1, max_length=64)]
    protocol: Annotated[str, Field(min_length=1, max_length=128)]
    capabilities: Annotated[tuple[Capability, ...], Field(min_length=1, max_length=64)]
    billing_components: Annotated[tuple[BillingComponent, ...], Field(min_length=1, max_length=16)]
    quota_pool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]
    weight: Annotated[StrictInt, Field(ge=1, le=64)]
    enabled: StrictBool

    @field_validator("capabilities", "billing_components", "quota_pool_ids")
    @classmethod
    def _normalize_sets(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        """Operation for normalize sets."""
        return tuple(sorted(values, key=str))

    @model_validator(mode="after")
    def _unique_sets(self) -> ModelShard:
        """Operation for unique sets."""
        _require_unique(self.capabilities, "capabilities")
        _require_unique(self.billing_components, "billing_components")
        _require_unique(self.quota_pool_ids, "quota_pool_ids")
        if self.region == "global" or self.provider_model_version == "latest":
            raise ValueError("shards require explicit region and model version")
        return self


class ModelAlias(ClosedModel):
    """Type for ModelAlias."""

    logical_alias: Identifier
    profile_id: Identifier
    strategy: AllocationStrategy
    affinity: AssignmentAffinity
    eligible_shard_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]
    price_schedule_id: Identifier

    @field_validator("eligible_shard_ids")
    @classmethod
    def _normalize_shards(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Operation for normalize shards."""
        return tuple(sorted(values))

    @model_validator(mode="after")
    def _unique_shards(self) -> ModelAlias:
        """Operation for unique shards."""
        _require_unique(self.eligible_shard_ids, "eligible_shard_ids")
        if self.strategy is AllocationStrategy.FIXED_V1 and len(self.eligible_shard_ids) != 1:
            raise ValueError("fixed-v1 requires exactly one eligible shard")
        return self
