"""Pack-authored model demand without deployment policy or credentials."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from shared.model_access.core_models import (
    AccessLimits,
    AllocationStrategy,
    Capability,
    ClosedModel,
    Identifier,
    Region,
    ScenarioNeed,
)


class PackModelNeed(ClosedModel):
    """Portable model demand bound to the installed pack digest by Shifter."""

    workload_role: Identifier
    profile_id: Identifier
    required: StrictBool
    required_capabilities: Annotated[tuple[Capability, ...], Field(max_length=64)]
    allowed_capabilities: Annotated[tuple[Capability, ...], Field(min_length=1, max_length=64)]
    allowed_strategies: Annotated[tuple[AllocationStrategy, ...], Field(min_length=1, max_length=2)]
    data_regions: Annotated[tuple[Region, ...], Field(min_length=1, max_length=32)]
    limits: AccessLimits

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        if not set(self.required_capabilities).issubset(self.allowed_capabilities):
            raise ValueError("required capabilities must be allowed")
        for values in (
            self.required_capabilities,
            self.allowed_capabilities,
            self.allowed_strategies,
            self.data_regions,
        ):
            if len(values) != len(set(values)):
                raise ValueError("model need lists must not contain duplicate values")
        return self


class PackModelNeedsDeclaration(ClosedModel):
    """Closed, credential-free model demand shipped by a pack author."""

    contract_version: Literal["model-access-pack/v1"]
    needs: dict[Identifier, PackModelNeed] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        if any(role != need.workload_role for role, need in self.needs.items()):
            raise ValueError("model need keys must match their workload roles")
        return self

    def bind_to_digest(self, digest: str) -> dict[str, dict[str, object]]:
        """Create the existing Shifter-owned overlay for exact installed bytes."""
        return {
            role: ScenarioNeed(
                contract_version="model-access-scenario/v1",
                scenario_digest=digest,
                **need.model_dump(mode="python"),
            ).model_dump(mode="json")
            for role, need in self.needs.items()
        }
