"""A receipt, a stale proof, and a mismatched guest can never prove realization."""

from copy import deepcopy
from dataclasses import replace

import pytest
from raes.parser import parse_sdl
from raes_contracts.runtime_state import RuntimeSnapshot
from raes_runtime import RuntimeManager

from shared.raes.completion import completed_snapshot, load_serialized_plan
from shared.raes.completion_evidence import (
    MAX_COMPLETION_INSTANCES,
    MAX_COMPLETION_RESOURCES,
    build_completion_evidence,
    validate_completion_evidence,
)
from shared.raes.dispatch_port import ShifterDispatchResult
from shared.raes.runtime_target import ShifterProvisioner, create_shifter_backend_target, serialize_provisioning_plan


def _scenario():
    return parse_sdl("""name: completion-probe
nodes:
  web:
    type: compute
    os: linux
    os_distribution: ubuntu
    os_version: "22.04"
realization:
  constraints:
    - field_pointer: /nodes/web
      concern: compute-substrate
      posture: exact
      domain: {kind: exact, value: virtual-machine}
""")


class _Port:
    def __init__(self):
        self.plans = []

    def realize(self, plan, participant_access=()):
        self.plans.append(plan)
        return ShifterDispatchResult("request", True, "accepted")


def _plan():
    scenario = _scenario()
    execution = RuntimeManager(create_shifter_backend_target(port=_Port(), scenario=scenario)).plan(scenario)
    assert not any(item.is_error for item in execution.diagnostics)
    return replace(execution.provisioning, operation_id="observed-operation")


def _serialized(plan):
    target = create_shifter_backend_target(port=_Port(), scenario=_scenario())
    return serialize_provisioning_plan(plan, backend_realization_envelope=target.manifest.realization_envelope)


def _evidence(plan, serialized=None):
    return build_completion_evidence(
        serialized or _serialized(plan),
        resources=[{"address": "provision.node.web", "resource_type": "node", "status": "provisioned"}],
        operating_systems=[
            {"instance_key": "provision.node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
        ],
        compute_substrates=[{"instance_key": "provision.node.web#0", "value": "virtual-machine"}],
    )


def test_enqueue_is_a_receipt_and_apply_cannot_echo_it_as_realization():
    port = _Port()
    backend = ShifterProvisioner(port)
    assert backend.enqueue(_plan()).accepted
    snapshot = RuntimeSnapshot()
    result = backend.apply(_plan(), snapshot)
    assert not result.success
    assert result.snapshot.entries == {}
    assert result.changed_addresses == []


def test_transport_preserves_semantics_and_observed_completion_passes():
    plan = _plan()
    serialized = _serialized(plan)
    restored = load_serialized_plan(serialized)
    assert restored == plan
    snapshot = completed_snapshot(restored, _evidence(plan), serialized_plan=serialized)
    assert snapshot.entries["provision.node.web"].status == "ready"
    assert snapshot.realization_observations[0].operating_system.version == "22.04"


def test_completion_cannot_pair_evidence_for_one_serialized_plan_with_another_plan_object():
    plan = _plan()
    altered = deepcopy(_serialized(plan))
    altered["resources"]["provision.node.web"]["payload"]["name"] = "different-node"
    evidence = _evidence(plan, altered)

    with pytest.raises(ValueError, match="immutable serialized plan"):
        completed_snapshot(plan, evidence, serialized_plan=altered)


def test_published_completion_cardinality_fits_the_byte_transport():
    evidence = {
        "schema_version": "shifter-raes-completion-v1",
        "plan_digest": "sha256:" + "a" * 64,
        "operation_id": "o" * 128,
        "generation_id": "g" * 128,
        "resources": [
            {
                "address": f"{index:03d}" + "a" * 253,
                "resource_type": "r" * 64,
                "status": "s" * 64,
            }
            for index in range(MAX_COMPLETION_RESOURCES)
        ],
        "operating_systems": [
            {
                "instance_key": f"{index:03d}" + "i" * 257,
                "family": "f" * 128,
                "distribution": "d" * 128,
                "version": "v" * 128,
            }
            for index in range(MAX_COMPLETION_INSTANCES)
        ],
        "compute_substrates": [
            {"instance_key": f"{index:03d}" + "i" * 257, "value": "v" * 128}
            for index in range(MAX_COMPLETION_INSTANCES)
        ],
    }

    assert validate_completion_evidence(evidence) == evidence


@pytest.mark.parametrize("mutation", ["missing", "tampered", "other-scenario"])
def test_completion_requires_the_exact_runtime_selected_carrier(mutation):
    plan = _plan()
    serialized = deepcopy(_serialized(plan))
    if mutation == "missing":
        serialized["backend_realization_envelope"] = None
    elif mutation == "tampered":
        serialized["backend_realization_envelope"]["expression"]["domains"]["scenario-name"]["value"] = "other"
    else:
        other = parse_sdl("""name: other
nodes:
  host: {type: compute}
""")
        serialized["backend_realization_envelope"] = create_shifter_backend_target(
            port=_Port(), scenario=other
        ).manifest.realization_envelope.model_dump(mode="json")

    with pytest.raises(ValueError):
        completed_snapshot(plan, _evidence(plan, serialized), serialized_plan=serialized)


@pytest.mark.parametrize("mutation", ["stale", "missing-os", "wrong-os", "wrong-substrate", "missing-resource"])
def test_invalid_observations_cannot_satisfy_the_plan(mutation):
    plan = _plan()
    evidence = deepcopy(_evidence(plan))
    if mutation == "stale":
        evidence["operation_id"] = "other-operation"
    elif mutation == "missing-os":
        evidence["operating_systems"] = []
    elif mutation == "wrong-os":
        evidence["operating_systems"][0]["version"] = "24.04"
    elif mutation == "wrong-substrate":
        evidence["compute_substrates"][0]["value"] = "container"
    else:
        evidence["resources"] = []
    with pytest.raises(ValueError):
        completed_snapshot(plan, evidence, serialized_plan=_serialized(plan))
