"""Join native admission to the public planner's compiled artifact availability seam."""

from collections.abc import Callable, Mapping
from dataclasses import replace

from raes.artifact_requirements import ArtifactRequirement
from raes.scenario import ExpandedScenario, InstantiatedScenario, Scenario
from raes_contracts.artifact_requirements import ArtifactAvailabilityContext, ArtifactRequirementAvailability
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.models.runtime_model import ExecutionPlan
from raes_runtime import RuntimeManager, RuntimeTarget

from shared.raes.artifact_inventory import ArtifactSupply, build_artifact_supply
from shared.raes.artifact_resolution import ArtifactResolutionStatus, resolve_artifact_requirement
from shared.raes.manifest import shifter_artifact_mechanism_capabilities, shifter_backend_apparatus


def _compiled_requirements(
    scenario: Scenario | ExpandedScenario | InstantiatedScenario,
    parameters: Mapping[str, object] | None,
) -> dict[str, ArtifactRequirement]:
    """Handle compiled requirements."""
    compiled = compile_scenario_runtime_model(scenario, parameters=parameters)
    requirements: dict[str, ArtifactRequirement] = {}
    for item in compiled.realization_requirements:
        if item.artifact_requirement is None:
            continue
        if item.address in requirements:
            raise ValueError("compiled artifact requirement address is ambiguous")
        requirements[item.address] = item.artifact_requirement
    return requirements


def _artifact_supply(
    requirements: Mapping[str, ArtifactRequirement],
    supply_provider: Callable[
        [Mapping[str, ArtifactRequirement]], ArtifactSupply | Mapping[str, ArtifactRequirementAvailability]
    ]
    | None,
) -> ArtifactSupply:
    """Handle artifact supply."""
    supplied = supply_provider(requirements) if supply_provider is not None and requirements else None
    if isinstance(supplied, ArtifactSupply):
        return supplied
    if supplied is not None:
        return ArtifactSupply(supplied, (), ())
    return build_artifact_supply(requirements, [])


def _availability_facts(
    requirements: Mapping[str, ArtifactRequirement], supply: ArtifactSupply, capabilities: list[str]
) -> list[ArtifactRequirementAvailability]:
    """Handle availability facts."""
    facts = []
    for address, requirement in requirements.items():
        result = resolve_artifact_requirement(
            requirement,
            address=address,
            capabilities=capabilities,
            availability=supply.availability.get(address),
            backend=shifter_backend_apparatus(),
            prepared_materializations=supply.materializations,
        )
        if result.status is not ArtifactResolutionStatus.SATISFIED:
            continue
        disclosure = result.disclosure
        if disclosure is None:
            raise ValueError("satisfied artifact resolution omitted its disclosure")
        facts.append(
            ArtifactRequirementAvailability(
                address=address,
                available_artifact_digests=[disclosure.artifact.digest],
                available_candidate_ids=[disclosure.candidate_id] if disclosure.candidate_id else [],
                verified_locked_input_ids=disclosure.locked_input_ids,
                satisfied_constraint_ids=disclosure.satisfied_constraint_ids,
                available_materialization_specification_digests=(
                    [disclosure.materialization_specification_digest]
                    if disclosure.materialization_specification_digest
                    else []
                ),
                verified_integrity_refs=disclosure.integrity_refs,
                verified_provenance_refs=disclosure.provenance_refs,
            )
        )
    return facts


def plan_with_artifact_supply(
    scenario: Scenario | ExpandedScenario | InstantiatedScenario,
    target: RuntimeTarget,
    *,
    parameters: Mapping[str, object] | None = None,
    supply_provider: Callable[
        [Mapping[str, ArtifactRequirement]], ArtifactSupply | Mapping[str, ArtifactRequirementAvailability]
    ]
    | None = None,
) -> tuple[ExecutionPlan, RuntimeTarget]:
    """Give RAES only complete admitted facts, keyed by its actual compiled addresses.

    Publication requirement addresses and planner resource addresses are different
    public contracts. Compile to obtain the latter; never translate strings or
    copy another requirement's partial availability into this concern.
    """
    requirements = _compiled_requirements(scenario, parameters)
    supply = _artifact_supply(requirements, supply_provider)
    capabilities = list(shifter_artifact_mechanism_capabilities())
    for capability in supply.capabilities:
        if capability not in capabilities:
            capabilities.append(capability)
    declarations = tuple(
        replace(declaration, artifact_mechanisms=tuple(capabilities))
        if declaration.domain == "runtime-realization"
        else declaration
        for declaration in target.manifest.realization_support
    )
    target = replace(target, manifest=replace(target.manifest, realization_support=declarations))
    facts = _availability_facts(requirements, supply, capabilities)
    return RuntimeManager(target).plan(
        scenario, parameters=parameters, artifact_availability=ArtifactAvailabilityContext(requirements=facts)
    ), target
