"""Installed preparation adapter contracts and joins to public RAES permission.

The manifest is deployment-local executable registration, not portable scenario
intent. It grants no cloud authority and makes no availability or verification
claim. Public RAES models remain the owners of profiles, specifications, locks
and permitted routes; the service supplies a separately authorized registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from raes.artifact_requirements import (
    ArtifactLockedInput,
    ArtifactMaterializationSpecification,
    ArtifactRequirement,
    ArtifactSatisfactionRoute,
)
from raes.explicitness import ExplicitnessClass
from raes.scenarios import ScenarioError, load_scenario
from raes_env_packs.publication import authored_artifact_requirements

from shared.exceptions import ValidationError as PreparationContractError
from shared.operation_envelope import canonical_payload_digest
from shared.preparation_grant import Identifier, ImageDigest, Permission
from shared.raes.preparation_inputs import BoundInput, load_input_material

MAX_MANIFEST_BYTES = 65536
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


def load_preparation_requirement(scenario_path: Path, address: str) -> ArtifactRequirement:
    """Keep upstream loading and compiled-address semantics behind shared.raes."""
    try:
        requirement = authored_artifact_requirements([load_scenario(scenario_path)]).get(address)
    except (ScenarioError, ValueError) as exc:
        raise PreparationContractError("The authored preparation requirement is unavailable") from exc
    if requirement is None:
        raise PreparationContractError("The authored preparation requirement is unavailable")
    return requirement


def load_preparation_input_bindings(scenario_path: Path, requirement: ArtifactRequirement) -> list[BoundInput]:
    """Read from the canonical single direct SDL pack selected by trusted staging."""
    if scenario_path.parent.name != "sdl":
        raise PreparationContractError("The preparation pack layout is unavailable")
    try:
        return load_input_material(scenario_path.parent.parent, load_scenario(scenario_path), requirement.locked_inputs)
    except (OSError, ValueError, ScenarioError) as exc:
        raise PreparationContractError("The preparation input material is unavailable") from exc


class PreparationPackage(BaseModel):
    """Trusted CMS projection after package integrity and conformance checks.

    HTTP callers identify registered packages; they never submit this projection.
    The engine still validates the public requirement and exact adapter join.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: Annotated[str, Field(min_length=1, max_length=256)]
    package_digest: Digest
    lock_digest: Digest | Literal[""] = ""
    requirement_address: Annotated[str, Field(min_length=1, max_length=1024)]
    requirement: ArtifactRequirement
    specification_id: Annotated[str, Field(min_length=1, max_length=256)]
    input_bindings: list[BoundInput] = Field(min_length=1, max_length=64)


class AdapterSpecification(BaseModel):
    """Exact specification and locks implemented by this immutable adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: ArtifactMaterializationSpecification
    locked_inputs: list[ArtifactLockedInput] = Field(max_length=64)
    constraint_kinds: list[Identifier] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_input_set(self) -> AdapterSpecification:
        """A named lock is not enough: require a complete unambiguous identity set."""
        ids = [item.input_id for item in self.locked_inputs]
        if len(ids) != len(set(ids)) or set(ids) != set(self.reference.locked_input_ids):
            raise ValueError("specification locks must exactly match the declared input set")
        if len(self.constraint_kinds) != len(set(self.constraint_kinds)):
            raise ValueError("constraint kinds must be unique")
        return self


class AdapterManifest(BaseModel):
    """Bounded immutable registration for one compatible private or built-in image.

    A new backend, worker protocol or verification protocol requires platform
    support. Another adapter implementing an existing one is ordinary tenant
    data. Service accounts, pull credentials, budgets and authority are granted
    separately; accepting this manifest never grants them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["shifter.artifact-preparation/v1"]
    adapter_id: Identifier
    version: Identifier
    backend: Literal["gce"]
    worker_image: ImageDigest
    verifier_image: ImageDigest
    verification_contract: Literal["shifter.gce-raw-disk/v1"]
    required_permissions: list[Permission] = Field(min_length=1, max_length=2)
    specifications: list[AdapterSpecification] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_registration(self) -> AdapterManifest:
        """Reject ambiguous entries and oversized private registration data."""
        ids = [item.reference.specification_id for item in self.specifications]
        if len(ids) != len(set(ids)):
            raise ValueError("specification identities must be unique")
        if len(self.required_permissions) != len(set(self.required_permissions)):
            raise ValueError("required permissions must be unique")
        if len(self.model_dump_json().encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ValueError("adapter manifest exceeds the size limit")
        return self

    @property
    def digest(self) -> str:
        """Bind every operational manifest field using the canonical wire digest."""
        return canonical_payload_digest(self.model_dump(mode="json"))


@dataclass(frozen=True)
class PreparationSelection:
    """Permission selected before execution, with no assertion of verified input."""

    specification: ArtifactMaterializationSpecification
    route: ArtifactSatisfactionRoute
    locked_inputs: tuple[ArtifactLockedInput, ...]


def select_preparation(
    requirement: ArtifactRequirement | None,
    adapter: AdapterManifest,
    specification_id: str,
) -> PreparationSelection:
    """Join explicit author permission to an exact installed implementation.

    This is preparation admission, not artifact satisfaction. A selection still
    requires authorized grants, actual input verification, execution and output
    admission. Absent, exact and open requirements cannot enter this operation.
    """
    if requirement is None or requirement.explicitness is not ExplicitnessClass.CONSTRAINED:
        raise PreparationContractError("This requirement does not permit artifact preparation")
    installed = _installed_specification(requirement, adapter, specification_id)
    declared = {item.input_id: item for item in requirement.locked_inputs}
    implemented = {item.input_id: item for item in installed.locked_inputs}
    if declared != implemented:
        raise PreparationContractError("The complete fixed input identities do not match")
    if any(item.kind not in installed.constraint_kinds for item in requirement.constraints):
        raise PreparationContractError("The adapter cannot verify every authored constraint")
    route = _permitted_preparation_route(requirement, installed.reference.profile)
    return PreparationSelection(installed.reference, route, tuple(installed.locked_inputs))


def _installed_specification(
    requirement: ArtifactRequirement, adapter: AdapterManifest, specification_id: str
) -> AdapterSpecification:
    """Handle installed specification."""
    installed = next(
        (item for item in adapter.specifications if item.reference.specification_id == specification_id), None
    )
    if installed is None or installed.reference not in requirement.materialization_specifications:
        raise PreparationContractError("No exact installed materialization specification matches")
    return installed


def _permitted_preparation_route(requirement: ArtifactRequirement, profile: str) -> ArtifactSatisfactionRoute:
    """Handle permitted preparation route."""
    route = next(
        (
            item
            for item in requirement.permitted_routes
            if item.mechanism == profile and item.acquisition == "none" and item.timing == "backend-preparation"
        ),
        None,
    )
    if route is None:
        raise PreparationContractError("The author did not permit this preparation route")
    return route
