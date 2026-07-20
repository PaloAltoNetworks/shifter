"""Feature-shape admission tests for the ACES-native runtime target."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from aces_contracts.planning import ChangeAction, PlannedResource, ProvisioningPlan, ProvisionOp, RuntimeDomain
from aces_contracts.runtime_state import RuntimeSnapshot

from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.runtime_target import NODE_RESOURCE_TYPE, ShifterProvisioner, interpret_provisioning_plan


@dataclass
class FakeDispatchPort:
    """Recording dispatch port used to prove rejected features never dispatch."""

    plans: list = field(default_factory=list)

    def realize(self, compiled_plan) -> ShifterDispatchResult:
        self.plans.append(compiled_plan)
        return ShifterDispatchResult(
            request_id="11111111-1111-1111-1111-111111111111",
            accepted=True,
            status="accepted",
            range_id="rng-1",
        )


def _node() -> PlannedResource:
    return PlannedResource(
        address="provision.node.a",
        domain=RuntimeDomain.PROVISIONING,
        resource_type=NODE_RESOURCE_TYPE,
        payload={
            "name": "a",
            "node_name": "a",
            "node_type": "vm",
            "os_family": "linux",
            "count": 1,
            "spec": {"node": {"type": "vm", "os": "linux"}, "infrastructure": {"links": [], "count": 1}},
        },
    )


def _feature_binding(
    *,
    source: str | None = "nginx",
    feature_type: str = "service",
    destination: str | None = None,
    environment: dict[str, str] | None = None,
) -> PlannedResource:
    template: dict[str, object] = {"type": feature_type}
    if source is not None:
        template["source"] = {"name": source}
    if destination is not None:
        template["destination"] = destination
    if environment is not None:
        template["environment"] = environment
    return PlannedResource(
        address="provision.feature.payload",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="feature-binding",
        payload={
            "name": "payload",
            "feature_name": "payload",
            "node_address": "provision.node.a",
            "spec": {"template": template},
        },
    )


def _plan(feature: PlannedResource) -> ProvisioningPlan:
    resources = {_node().address: _node(), feature.address: feature}
    return ProvisioningPlan(resources=resources, operations=[])


@pytest.mark.parametrize("feature_type", ["service", "artifact", "configuration"])
def test_evidence_backed_feature_shapes_are_accepted(feature_type: str) -> None:
    destination = None if feature_type == "service" else "/opt/aces/payload"
    serialized, diagnostics = interpret_provisioning_plan(
        _plan(_feature_binding(feature_type=feature_type, destination=destination))
    )
    assert serialized is not None
    assert not any(d.is_error for d in diagnostics)


@pytest.mark.parametrize(
    ("feature", "expected_code"),
    [
        (_feature_binding(feature_type="driver"), "shifter-provisioner.unsupported-feature-type"),
        (_feature_binding(source=None), "shifter-provisioner.feature-source-required"),
        (_feature_binding(feature_type="artifact"), "shifter-provisioner.feature-destination-required"),
        (
            _feature_binding(environment={"TOKEN": "must-not-leak"}),
            "shifter-provisioner.feature-environment-unsupported",
        ),
    ],
)
def test_unsupported_feature_shapes_fail_before_dispatch(feature: PlannedResource, expected_code: str) -> None:
    serialized, diagnostics = interpret_provisioning_plan(_plan(feature))
    assert serialized is None
    assert any(d.is_error and d.code == expected_code for d in diagnostics)
    assert all("must-not-leak" not in d.message for d in diagnostics)


def test_operation_only_feature_environment_fails_and_does_not_dispatch() -> None:
    template = {"type": "service", "source": {"name": "nginx"}, "environment": {"TOKEN": "secret"}}
    operation = ProvisionOp(
        action=ChangeAction.CREATE,
        address="provision.feature.op",
        resource_type="feature-binding",
        payload={
            "feature_name": "nginx",
            "node_address": "provision.node.a",
            "spec": {"template": template},
        },
    )
    port = FakeDispatchPort()
    plan = ProvisioningPlan(resources={_node().address: _node()}, operations=[operation])

    result = ShifterProvisioner(port).apply(plan, RuntimeSnapshot())

    assert result.success is False
    assert port.plans == []
    assert any(d.code == "shifter-provisioner.feature-environment-unsupported" for d in result.diagnostics)
    assert all("secret" not in d.message for d in result.diagnostics)
