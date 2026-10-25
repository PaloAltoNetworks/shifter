"""Closed admission inputs for Engine's durable model-capacity decision (M03).

These are internal service contracts, not additional scenario fields or guest
credentials. Observation producers run before the allocation transaction.
"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from shared.model_access.admission import EventModelDemand
from shared.model_access.core_models import ClosedModel, Digest, Identifier, OwnedReference, ScenarioNeed
from shared.model_access.sources import ModelSourceSponsorship

Quantity = Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]


class ModelWarmScope(ClosedModel):
    """Existing warm-ledger identity and idle window, without a fabricated event."""

    scope_id: UUID
    draw_key: UUID
    window_start: datetime
    window_end: datetime
    generation_id: UUID
    authority_revisions: tuple["AuthorityRevision", ...]


class AuthorityRevision(ClosedModel):
    """Expected revision of an incumbent Engine authority fence."""

    authority_ref: OwnedReference
    authority_revision: Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]


class ModelQuotaObservation(ClosedModel):
    """Bounded provider observation, or explicitly reviewed application cap."""

    quota_pool_id: Identifier
    catalog_digest: Digest
    source: Literal["observed_provider", "application_cap"]
    observed_at: datetime
    valid_until: datetime
    limit: Quantity
    usage: Quantity
    healthy_shard_ids: Annotated[tuple[Identifier, ...], Field(max_length=256)]

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        """Require an explicit validity interval and unique health identities."""
        if self.observed_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("observation requires timezone")
        if self.valid_until <= self.observed_at:
            raise ValueError("observation interval invalid")
        if len(self.healthy_shard_ids) != len(set(self.healthy_shard_ids)):
            raise ValueError("duplicate health identity")
        return self


class ModelAllocationRequest(ClosedModel):
    """Authorized launch identity and demand, supplied through downward bridges."""

    deployment_id: UUID
    request_id: UUID
    operation_id: UUID
    range_id: UUID
    draw_key: UUID
    owner_ref: OwnedReference
    subject_ref: OwnedReference
    scope_kind: Literal["event", "standalone", "warm"]
    scope_id: UUID
    need: ScenarioNeed
    demand: EventModelDemand
    window_start: datetime
    window_end: datetime
    authority_revisions: Annotated[tuple[AuthorityRevision, ...], Field(min_length=1, max_length=128)]
    source_policy_revision: Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] = Field(
        default=0, exclude_if=lambda value: value == 0
    )
    preparation_authority: OwnedReference | None = None

    def _effective_authority(self) -> OwnedReference:
        """Validate and return the owner authority used for preparation."""
        authority = self.preparation_authority or self.owner_ref
        if self.preparation_authority is None:
            return authority
        allowed = {"event": ("ctf", "spare:"), "warm": ("engine", "warm-generation:")}
        owner, prefix = allowed.get(self.scope_kind, (None, ""))
        if authority.owner != owner or not authority.reference.startswith(prefix):
            raise ValueError("invalid system preparation authority")
        UUID(authority.reference.removeprefix(prefix))
        return authority

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        """Require one exact workload, bounded window and complete unique fences."""
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("window requires timezone")
        if self.window_start >= self.window_end:
            raise ValueError("window invalid")
        if self.need.workload_role != self.demand.workload_role:
            raise ValueError("workload mismatch")
        refs = [(item.authority_ref.owner, item.authority_ref.reference) for item in self.authority_revisions]
        authority = self._effective_authority()
        if len(refs) != len(set(refs)) or (authority.owner, authority.reference) not in refs:
            raise ValueError("owner authority missing or duplicated")
        return self


class SystemPreparationAuthority(ClosedModel):
    """CTF-projected authority to prepare, never activate, an inactive spare owner."""

    kind: Literal["ctf_spare"] = "ctf_spare"
    owner_ref: OwnedReference
    spare_id: UUID

    @property
    def authority_ref(self) -> OwnedReference:
        return OwnedReference(owner="ctf", reference=f"spare:{self.spare_id}")


class WarmPreparationAuthority(ClosedModel):
    """Ledger-bound authority for an inactive warm owner, never claimant access."""

    kind: Literal["warm_pool"] = "warm_pool"
    owner_ref: OwnedReference
    generation_id: UUID

    @property
    def authority_ref(self) -> OwnedReference:
        return OwnedReference(owner="engine", reference=f"warm-generation:{self.generation_id}")


class ModelLaunchScope(ClosedModel):
    """Owner-supplied event or explicitly non-event demand and stable draw."""

    kind: Literal["event", "standalone", "warm"]
    scope_id: UUID
    draw_key: UUID
    subject_ref: OwnedReference
    window_start: datetime
    window_end: datetime
    demands: Annotated[tuple[EventModelDemand, ...], Field(min_length=1, max_length=64)]
    authority_revisions: Annotated[tuple[AuthorityRevision, ...], Field(max_length=128)] = ()
    source_policy_revision: Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] = Field(
        default=0, exclude_if=lambda value: value == 0
    )
    source_sponsorship: ModelSourceSponsorship | None = Field(default=None, exclude_if=lambda value: value is None)
    system_preparation: (
        Annotated[SystemPreparationAuthority | WarmPreparationAuthority, Field(discriminator="kind")] | None
    ) = None

    def _validate_system_preparation(self) -> None:
        """Bind a system owner to the matching scope and captured fences."""
        if self.system_preparation is None:
            return
        authority = self.system_preparation.authority_ref
        refs = {item.authority_ref for item in self.authority_revisions}
        expected_kind = "event" if self.system_preparation.kind == "ctf_spare" else "warm"
        if self.kind != expected_kind or authority not in refs:
            raise ValueError("system preparation scope authority missing")
        if self.kind == "event" and OwnedReference(owner="ctf", reference=f"event-launch:{self.scope_id}") not in refs:
            raise ValueError("system preparation requires event authority")

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Reject ambiguous roles and windows at the downward service boundary."""
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None or self.window_end <= self.window_start:
            raise ValueError("invalid scope window")
        roles = [item.workload_role for item in self.demands]
        if len(roles) != len(set(roles)):
            raise ValueError("duplicate demand role")
        self._validate_system_preparation()
        return self


class ModelLaunchPreparation(ClosedModel):
    """Frozen launch inputs referencing, but never replacing, owner authority."""

    request_id: UUID
    owner_ref: OwnedReference
    needs: Annotated[tuple[ScenarioNeed, ...], Field(min_length=1, max_length=64)]
    scope: ModelLaunchScope | None = None
    authority_revisions: Annotated[tuple[AuthorityRevision, ...], Field(max_length=128)] = ()
    unavailable_reason: Literal["allocation.policy_unavailable"] | None = None

    def _validate_unavailable(self) -> None:
        """Ensure an unavailable optional launch carries no residual authority."""
        if any(need.required for need in self.needs):
            raise ValueError("required preparation cannot be absent")
        if self.scope is not None or self.authority_revisions:
            raise ValueError("unavailable preparation cannot retain authority")

    def _validate_available(self, roles: list[str]) -> None:
        """Ensure available preparation has complete matching scope and ownership."""
        if self.scope is None or not self.authority_revisions:
            raise ValueError("available preparation requires scope and authority")
        if set(roles) != {item.workload_role for item in self.scope.demands}:
            raise ValueError("launch workload mismatch")
        if self.scope.system_preparation is not None and self.scope.system_preparation.owner_ref != self.owner_ref:
            raise ValueError("system preparation owner mismatch")

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        """Every authored workload has exactly one explicit demand."""
        roles = [item.workload_role for item in self.needs]
        if len(roles) != len(set(roles)):
            raise ValueError("launch workload mismatch")
        if len({need.scenario_digest for need in self.needs}) != 1:
            raise ValueError("launch package mismatch")
        if self.unavailable_reason:
            self._validate_unavailable()
        else:
            self._validate_available(roles)
        return self
