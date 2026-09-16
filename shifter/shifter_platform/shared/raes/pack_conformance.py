"""Structural pack conformance, separate from deployment readiness and inventory."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from raes.scenarios import load_scenario
from raes_runtime import RuntimeManager

from shared.raes.dispatch_port import ShifterDispatchResult
from shared.raes.participant_access import project_participant_access
from shared.raes.runtime_target import NODE_RESOURCE_TYPE, ShifterProvisioner, create_shifter_backend_target

# These are runtime supply/installation questions. A passed conformance report
# never answers them; ordinary launch re-runs the real planner with admitted
# tenant facts. Everything else remains a conformance failure.
_DEFERRED_ARTIFACT_CODES = frozenset(
    {
        "artifact.missing-locked-input",
        "artifact.unavailable-candidate",
        "artifact.unavailable-exact-artifact",
        "artifact.unavailable-materialization-specification",
        "artifact.unsatisfied-constraint",
        "artifact.unsupported-backend-mechanism",
    }
)


class ContractValidationPort:
    """Conformance must never dispatch a range or fabricate an accepted receipt."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id

    def realize(
        self,
        compiled_plan: dict[str, Any],
        participant_access: Sequence[Any] = (),
    ) -> ShifterDispatchResult:
        _ = (self.request_id, compiled_plan, participant_access)
        raise RuntimeError("contract validation cannot dispatch")


def validate_pack_contract(scenario_path: Path, request_id: str) -> None:
    """Compile the real SDL and validate backend structure without asserting supply."""
    scenario = load_scenario(scenario_path)
    target = create_shifter_backend_target(port=ContractValidationPort(request_id), scenario=scenario)
    execution = RuntimeManager(target).plan(scenario)
    artifact_addresses = {
        item.address for item in execution.model.realization_requirements if item.artifact_requirement
    }
    diagnostics = [*execution.diagnostics, *ShifterProvisioner.validate(execution.provisioning)]
    if (
        any(
            item.is_error and not (item.code in _DEFERRED_ARTIFACT_CODES and item.address in artifact_addresses)
            for item in diagnostics
        )
        or not execution.provisioning.resources
    ):
        raise ValueError("pack does not conform to the supported backend structure")
    project_participant_access(
        execution.model.participant_behaviors,
        node_addresses=frozenset(
            resource.address
            for resource in execution.provisioning.resources.values()
            if resource.resource_type == NODE_RESOURCE_TYPE
        ),
    )
