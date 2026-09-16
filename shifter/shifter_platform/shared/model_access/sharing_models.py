"""Immutable model-access sharing policy DTOs (PLAT-202)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from shared.model_access.core_models import (
    AssignmentAffinity,
    ClosedModel,
    Digest,
    Identifier,
    MembershipMode,
    OwnedReference,
    PositiveInt,
    SelectorIdentity,
    SelectorKind,
    SharingFacet,
    _require_unique,
)

# The 1,000-ID bound is aggregate across the complete selector definition, not
# per atomic member (a named union of 32 members must not smuggle 32,000 IDs).
# The per-field ``max_length`` above still bounds any single atomic selector.
_MAX_SELECTOR_IDS = 1000
# ``include_spares`` is meaningful only where the owning CTF adapter defines
# spare membership; every other selector kind rejects it rather than silently
# ignoring an operator's request for a semantics it does not have.
_SPARE_CAPABLE_KINDS = frozenset({SelectorKind.CTF_EVENT, SelectorKind.CTF_COHORT, SelectorKind.CTF_TEAM})


class SharingSelector(ClosedModel):
    """Type for SharingSelector."""

    kind: SelectorKind
    ids: Annotated[tuple[SelectorIdentity, ...], Field(max_length=1000)] = ()
    members: Annotated[tuple[SharingSelector, ...], Field(max_length=32)] = ()
    include_spares: StrictBool = False

    @field_validator("ids")
    @classmethod
    def _normalize_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Operation for normalize ids."""
        return tuple(sorted(values))

    @field_validator("members")
    @classmethod
    def _normalize_members(cls, values: tuple[SharingSelector, ...]) -> tuple[SharingSelector, ...]:
        """Operation for normalize members."""
        return tuple(sorted(values, key=lambda item: (item.kind.value, item.ids, item.include_spares)))

    @model_validator(mode="after")
    def _closed_shape(self) -> SharingSelector:
        """Operation for closed shape."""
        _require_unique(self.ids, "selector.ids")
        if self.include_spares and self.kind not in _SPARE_CAPABLE_KINDS:
            raise ValueError("include_spares is valid only for CTF event, cohort, or team selectors")
        if self.kind is SelectorKind.ALL_RANGES:
            if self.ids or self.members:
                raise ValueError("all_ranges has no ids, members, or spares flag")
        elif self.kind is SelectorKind.NAMED_COLLECTION:
            self._validate_named_collection()
        elif self.members or not self.ids:
            raise ValueError("atomic selectors require ids and no members")
        return self

    def _validate_named_collection(self) -> None:
        """Enforce the closed shape and aggregate bounds of a named union selector."""
        if self.ids or not self.members:
            raise ValueError("named_collection requires members and no ids")
        if any(member.kind is SelectorKind.NAMED_COLLECTION for member in self.members):
            raise ValueError("named collections cannot be recursively nested")
        member_keys = tuple((member.kind.value, member.ids, member.include_spares) for member in self.members)
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("named collection members must be unique")
        if sum(len(member.ids) for member in self.members) > _MAX_SELECTOR_IDS:
            raise ValueError("named collection exceeds the aggregate selector ID limit")


class AliasAffinity(ClosedModel):
    """Type for AliasAffinity."""

    logical_alias: Identifier
    affinity: AssignmentAffinity


class SharingPool(ClosedModel):
    """Type for SharingPool."""

    sharing_pool_id: Identifier
    routing_revision: PositiveInt
    alias_affinities: Annotated[tuple[AliasAffinity, ...], Field(max_length=64)] = ()
    provider_pool_ref: Identifier | None = None
    capacity_account_ref: Identifier | None = None
    spend_account_refs: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    rate_account_refs: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    concurrency_account_refs: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()

    @field_validator("alias_affinities")
    @classmethod
    def _normalize_aliases(cls, values: tuple[AliasAffinity, ...]) -> tuple[AliasAffinity, ...]:
        """Operation for normalize aliases."""
        return tuple(sorted(values, key=lambda item: item.logical_alias))

    @field_validator("spend_account_refs", "rate_account_refs", "concurrency_account_refs")
    @classmethod
    def _normalize_accounts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Operation for normalize accounts."""
        return tuple(sorted(values))

    @model_validator(mode="after")
    def _validate_pool(self) -> SharingPool:
        """Operation for validate pool."""
        aliases = tuple(item.logical_alias for item in self.alias_affinities)
        _require_unique(aliases, "alias_affinities.logical_alias")
        for field_name in ("spend_account_refs", "rate_account_refs", "concurrency_account_refs"):
            _require_unique(getattr(self, field_name), field_name)
        if not any(
            (
                self.alias_affinities,
                self.provider_pool_ref,
                self.capacity_account_ref,
                self.spend_account_refs,
                self.rate_account_refs,
                self.concurrency_account_refs,
            )
        ):
            raise ValueError("sharing pool must share at least one facet")
        return self


class SharingBinding(ClosedModel):
    """Type for SharingBinding."""

    contract_version: Literal["model-access-sharing/v1"]
    sharing_binding_id: Identifier
    deployment_id: UUID
    selector: SharingSelector
    membership_mode: MembershipMode
    membership_revision: PositiveInt
    authorized_publisher_ref: OwnedReference
    profile_id: Identifier | None = None
    sharing_pool_id: Identifier
    facets: Annotated[tuple[SharingFacet, ...], Field(min_length=1, max_length=7)]
    priority: Annotated[StrictInt, Field(ge=0, le=1000)] = 0
    effective_from: datetime
    effective_until: datetime
    definition_digest: Digest

    @field_validator("facets")
    @classmethod
    def _normalize_facets(cls, values: tuple[SharingFacet, ...]) -> tuple[SharingFacet, ...]:
        """Operation for normalize facets."""
        return tuple(sorted(values, key=str))

    @model_validator(mode="after")
    def _validate_binding(self) -> SharingBinding:
        """Operation for validate binding."""
        _require_unique(self.facets, "facets")
        if self.effective_from.tzinfo is None or self.effective_until.tzinfo is None:
            raise ValueError("effective interval must include timezones")
        if self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        if SharingFacet.PROFILE in self.facets and self.profile_id is None:
            raise ValueError("profile sharing requires profile_id")
        return self
