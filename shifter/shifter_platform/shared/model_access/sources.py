"""Closed tenant model-source intent and actor-selected routing references."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StrictBool, field_validator, model_validator

from shared.model_access.core_models import (
    ClosedModel,
    Currency,
    Identifier,
    NonNegativeInt,
    PositiveInt,
    Region,
    _require_unique,
)
from shared.model_access.provider_runtime import AuthenticationKind, ProviderKind, ProviderTarget


class ModelSourceConfiguration(ClosedModel):
    """A provider connection with explicit region, price and real quota identity."""

    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")]
    provider: ProviderKind
    authentication: AuthenticationKind
    model: Annotated[str, Field(pattern=r"^[a-zA-Z0-9@.:/-]{1,256}$")]
    region: Region
    project: Annotated[str, Field(max_length=30)] = ""
    principal: Annotated[str, Field(max_length=256)] = ""
    count_region: Annotated[str, Field(max_length=64)] = ""
    quota_identity: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9:/._@-]+$")]
    context_window_tokens: Annotated[int, Field(strict=True, ge=1, le=2_000_000)]
    tokens_per_minute: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    input_price_per_million: NonNegativeInt
    output_price_per_million: NonNegativeInt
    currency: Currency = Currency.USD
    price_valid_until: datetime
    # Registration alone grants nobody spending access. An admin explicitly
    # opts members in, or lists individual active actors permitted to select it.
    allow_organization_members: StrictBool = False
    allowed_user_ids: Annotated[tuple[PositiveInt, ...], Field(max_length=256)] = ()
    # OpenRouter execution pins the selected upstream; no hidden fallback pool.
    upstream_provider: Annotated[str, Field(max_length=100, pattern=r"^[a-zA-Z0-9 /._-]*$")] = ""

    @field_validator("allowed_user_ids")
    @classmethod
    def normalize_users(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate permitted user")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.price_valid_until.tzinfo is None or self.region == "global":
            raise ValueError("explicit price validity and data region required")
        if bool(self.upstream_provider) != (self.provider == "openrouter-v1"):
            raise ValueError("OpenRouter requires an explicit upstream provider")
        self.target(UUID(int=1), 1)
        return self

    @property
    def capacity_identity(self) -> str:
        """Cloud labels cannot split the same account/region application ceiling."""
        if self.provider == "vertex-v1":
            return f"project:{self.project}/region:{self.region}"
        if self.provider == "bedrock-v1":
            return f"account:{self.principal.split(':')[4]}/region:{self.region}"
        return self.quota_identity

    def target(self, source_id: UUID, revision: int) -> ProviderTarget:
        return ProviderTarget(
            shard_id=f"source-{source_id.hex}-v{revision}",
            provider=self.provider,
            authentication=self.authentication,
            region=self.region,
            model=self.model,
            credential_reference=f"source:{source_id}:{revision}",
            principal=self.principal,
            project=self.project,
            count_region=self.count_region,
            context_window_tokens=self.context_window_tokens,
        )


class SourceChoice(ClosedModel):
    """Revision-pinned, weighted source selection; it conveys no authority."""

    source_id: UUID
    revision: PositiveInt
    weight: Annotated[int, Field(strict=True, ge=1, le=64)] = 1


class AliasSourceSelection(ClosedModel):
    """One or several sources for a logical alias, separate from pack content."""

    logical_alias: Identifier
    sources: Annotated[tuple[SourceChoice, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len({item.source_id for item in self.sources}) != len(self.sources):
            raise ValueError("duplicate source selection")
        return self


class ModelSourceSelection(ClosedModel):
    """Owner-authored launch/event selection with optimistic revision control."""

    aliases: Annotated[tuple[AliasSourceSelection, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def unique_aliases(self) -> Self:
        _require_unique(tuple(item.logical_alias for item in self.aliases), "aliases")
        return self


class ModelSourceSponsorship(ClosedModel):
    """Server-projected source authority for event-funded participant ranges."""

    actor_id: PositiveInt
    organization_uuid: UUID
    workspace_id: PositiveInt
    selection: ModelSourceSelection
    administrative: StrictBool = False


@dataclass(frozen=True)
class ModelSourceUseScope:
    """CMS-authorized tenant membership, passed only across the internal seam.

    This is not a wire payload. Engine separately enforces each source's use
    grant and revision; CMS resolves live tenancy before constructing it.
    """

    actor_id: int
    organization_uuid: UUID
