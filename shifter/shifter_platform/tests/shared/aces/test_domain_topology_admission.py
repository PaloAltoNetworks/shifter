"""Admission tests for ACES 0.23 authored identity-domain topology (#1606)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from aces_contracts.diagnostics import Diagnostic, Severity
from aces_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from aces_contracts.runtime_state import RuntimeSnapshot, SnapshotEntry
from aces_processor.compiler import compile_runtime_model
from aces_processor.planner import plan as compile_plan
from aces_sdl.parser import parse_sdl

from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.manifest import create_shifter_backend_manifest
from shared.aces.runtime_target import ShifterProvisioner, interpret_provisioning_plan


@dataclass
class RecordingPort:
    """Record accepted serialized plans without performing I/O."""

    plans: list[dict] = field(default_factory=list)

    def realize(self, compiled_plan: dict) -> ShifterDispatchResult:
        self.plans.append(compiled_plan)
        return ShifterDispatchResult(
            request_id="11111111-1111-1111-1111-111111111111",
            accepted=True,
            status="accepted",
            range_id="rng-1",
        )


def _compiled_domain_plan(
    *,
    member_os: str = "windows",
    controller_count: int = 1,
    service_auth_method: str = "password",
    service_username: str = "svc-web",
    service_spn: str = "HTTP/member.corp.example",
    authority_effect: str = "",
) -> ProvisioningPlan:
    authority_effect_yaml = f"            {authority_effect}" if authority_effect else ""
    scenario = parse_sdl(
        """
        name: domain-topology-probe
        nodes:
          lan: {type: switch}
          dc: {type: vm, os: windows}
          member: {type: vm, os: __MEMBER_OS__}
        accounts:
          domain-admin:
            username: Administrator
            node: dc
__AUTHORITY_EFFECT__
          local-operator: {username: local-operator, node: member}
          web-service:
            username: __SERVICE_USERNAME__
            node: member
            auth_method: __SERVICE_AUTH_METHOD__
            spn: __SERVICE_SPN__
            domain_ref: corp
        identity_domains:
          corp:
            profile: active_directory
            dns_name: corp.example
            netbios_name: CORP
            authority_account_ref: domain-admin
        relationships:
          controller:
            type: domain_controller_for
            source: dc
            target: corp
            domain_controller: {}
          member-join:
            type: joins_domain
            source: member
            target: corp
            domain_join: {controller_refs: [dc]}
        infrastructure:
          lan:
            count: 1
            properties: {cidr: 10.70.0.0/24, gateway: 10.70.0.1}
          dc:
            count: __CONTROLLER_COUNT__
            links: [lan]
          member:
            count: 1
            links: [lan]
        """.replace("__MEMBER_OS__", member_os)
        .replace("__CONTROLLER_COUNT__", str(controller_count))
        .replace("__SERVICE_AUTH_METHOD__", service_auth_method)
        .replace("__SERVICE_USERNAME__", service_username)
        .replace("__SERVICE_SPN__", service_spn)
        .replace("__AUTHORITY_EFFECT__", authority_effect_yaml)
    )
    manifest = create_shifter_backend_manifest()
    return compile_plan(compile_runtime_model(scenario), manifest).provisioning


def test_real_compiled_domain_topology_is_admitted_and_dispatched() -> None:
    port = RecordingPort()

    result = ShifterProvisioner(port).apply(_compiled_domain_plan(), RuntimeSnapshot())

    assert result.success is True
    assert result.diagnostics == []
    assert len(port.plans) == 1


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"member_os": "linux"}, "shifter-provisioner.domain-member-os-unsupported"),
        ({"controller_count": 2}, "shifter-provisioner.domain-controller-cardinality-unsupported"),
        ({"service_auth_method": "publickey"}, "shifter-provisioner.domain-account-policy-unsupported"),
        ({"service_username": "Administrator"}, "shifter-provisioner.domain-account-duplicate"),
        ({"service_spn": "not-a-service-principal"}, "shifter-provisioner.account-spn-invalid"),
    ],
)
def test_backend_effect_policy_rejects_unsupported_domain_combinations_before_dispatch(
    overrides: dict[str, object], expected_code: str
) -> None:
    port = RecordingPort()

    result = ShifterProvisioner(port).apply(_compiled_domain_plan(**overrides), RuntimeSnapshot())

    assert result.success is False
    assert port.plans == []
    assert any(d.code == expected_code for d in result.diagnostics)


@pytest.mark.parametrize("authority_effect", ["groups: [ops]", "shell: /bin/bash", "home: /home/Administrator"])
def test_authority_local_account_effects_are_rejected_before_dispatch(authority_effect: str) -> None:
    port = RecordingPort()

    result = ShifterProvisioner(port).apply(
        _compiled_domain_plan(authority_effect=authority_effect),
        RuntimeSnapshot(),
    )

    assert result.success is False
    assert port.plans == []
    assert any(d.code == "shifter-provisioner.domain-authority-unsupported" for d in result.diagnostics)


def test_domain_topology_diagnostic_messages_are_replaced_without_changing_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_dns_name = "redaction-probe.example"
    sensitive_netbios_name = "REDACTION-PROBE"
    upstream_code = "provisioning.domain-topology.redaction-probe"
    upstream = Diagnostic(
        code=upstream_code,
        domain="provisioning",
        address="provision.node.dc",
        message=f"identity domain {sensitive_dns_name} ({sensitive_netbios_name}) is invalid",
        severity=Severity.ERROR,
    )
    monkeypatch.setattr(
        "shared.aces.domain_topology.domain_topology_plan_diagnostics",
        lambda *_args, **_kwargs: [upstream],
    )

    serialized, diagnostics = interpret_provisioning_plan(ProvisioningPlan(resources={}))

    assert serialized is None
    assert len(diagnostics) == 1
    assert diagnostics[0].code == upstream_code
    assert diagnostics[0].address == upstream.address
    assert diagnostics[0].message == ("authored identity-domain topology is invalid or unsupported by this backend")
    assert sensitive_dns_name not in diagnostics[0].message
    assert sensitive_netbios_name not in diagnostics[0].message


def test_malformed_domain_topology_fails_before_serialization() -> None:
    node = PlannedResource(
        address="provision.node.dc",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload={
            "name": "dc",
            "os_family": "windows",
            "spec": {"node": {"type": "vm", "os": "windows"}},
            "domain_topology": "active_directory",
        },
    )

    serialized, diagnostics = interpret_provisioning_plan(ProvisioningPlan(resources={node.address: node}))

    assert serialized is None
    assert any(d.code == "provisioning.domain-topology.binding-invalid" for d in diagnostics)


def test_apply_uses_snapshot_for_incremental_domain_topology() -> None:
    full_plan = _compiled_domain_plan()
    operations = {operation.address: operation for operation in full_plan.operations}
    snapshot = RuntimeSnapshot(
        entries={
            address: SnapshotEntry(
                address=operation.address,
                domain=RuntimeDomain.PROVISIONING,
                resource_type=operation.resource_type,
                payload=operation.payload,
                ordering_dependencies=operation.ordering_dependencies,
                refresh_dependencies=operation.refresh_dependencies,
            )
            for address in ("provision.node.dc", "provision.account.domain-admin")
            for operation in (operations[address],)
        }
    )
    incremental = ProvisioningPlan(operations=[operations["provision.node.member"]])
    port = RecordingPort()

    assert any(
        d.code == "provisioning.domain-topology.controller-unbound"
        for d in ShifterProvisioner(port).validate(incremental)
    )
    result = ShifterProvisioner(port).apply(incremental, snapshot)

    assert result.success is True
    assert result.diagnostics == []
    assert len(port.plans) == 1
