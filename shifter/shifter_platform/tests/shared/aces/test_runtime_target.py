"""Battery for the ACES-native RuntimeTarget provisioning backend (ADR-031, ADR-032).

Covers the interpret step (validate a compiled ProvisioningPlan, then serialize it
verbatim) on both hand-built plans and a plan compiled by the real aces-sdl
processor; the capability-envelope fail-closed negatives; apply/dispatch;
diagnostics sanitization (ADR-031-R4); and the registration/target shape.
Realization-time extraction (source->image, resources->sizing, acls) is the
provisioner's job and is covered in the provisioner's plan-accessor tests. The
live conformance probe (run_target_conformance) lives in
``test_backend_conformance_gate.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from aces_backend_protocols.capabilities import ProvisionerCapabilities
from aces_contracts.planning import ChangeAction, PlannedResource, ProvisioningPlan, ProvisionOp, RuntimeDomain
from aces_contracts.runtime_state import RuntimeSnapshot
from aces_runtime.manager import RuntimeManager
from aces_runtime.registry import BackendRegistry
from aces_sdl.parser import parse_sdl

from shared.aces.contracts import ACES_PROVISIONING_PLAN_CONTRACT_VERSION, SHIFTER_BACKEND_NAME
from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.manifest import create_shifter_backend_manifest
from shared.aces.runtime_target import (
    ACES_PROVISIONING_PLAN_KIND,
    NETWORK_RESOURCE_TYPE,
    NODE_RESOURCE_TYPE,
    ShifterProvisioner,
    create_shifter_backend_components,
    create_shifter_backend_target,
    interpret_provisioning_plan,
    register_shifter_backend,
)

REQUEST_ID = "11111111-1111-1111-1111-111111111111"

_FORBIDDEN_DIAGNOSTIC_SUBSTRINGS = (
    "terraform",
    "ssm",
    "ami-",
    "cidr",
    "subnet",
    "secret",
    "password",
    "credential",
    "token",
    "-----begin",
)


@dataclass
class FakeDispatchPort:
    """Recording dispatch port: no DB/cloud, returns an accepted result."""

    request_id: str = REQUEST_ID
    accepted: bool = True
    raises: Exception | None = None
    plans: list = field(default_factory=list)

    def realize(self, compiled_plan) -> ShifterDispatchResult:
        if self.raises is not None:
            raise self.raises
        self.plans.append(compiled_plan)
        return ShifterDispatchResult(
            request_id=self.request_id, accepted=self.accepted, status="accepted", range_id="rng-1"
        )


def _node(
    address: str,
    name: str,
    *,
    os_family: str = "linux",
    node_type: str = "vm",
    count: int = 1,
    links: tuple[str, ...] = (),
    acls: list | None = None,
    ram_bytes: int | None = 2 * 1024 * 1024 * 1024,
    cpu: int | None = 2,
    source: object = None,
    services: list | None = None,
) -> PlannedResource:
    node_spec: dict = {"type": node_type, "os": os_family}
    resources: dict = {}
    if ram_bytes is not None:
        resources["ram"] = ram_bytes
    if cpu is not None:
        resources["cpu"] = cpu
    if resources:
        node_spec["resources"] = resources
    if source is not None:
        node_spec["source"] = source
    if services is not None:
        node_spec["services"] = services
    infra: dict = {"links": list(links), "count": count}
    if acls is not None:
        infra["acls"] = acls
    return PlannedResource(
        address=address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type=NODE_RESOURCE_TYPE,
        payload={
            "name": name,
            "node_name": name,
            "node_type": node_type,
            "os_family": os_family,
            "count": count,
            "spec": {"node": node_spec, "infrastructure": infra},
        },
    )


def _network(address: str, name: str, *, cidr: str = "10.0.0.0/24", internal: bool = False) -> PlannedResource:
    return PlannedResource(
        address=address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type=NETWORK_RESOURCE_TYPE,
        payload={
            "name": name,
            "node_name": name,
            "spec": {
                "node": {"type": "switch"},
                "infrastructure": {"properties": {"cidr": cidr, "gateway": "10.0.0.1", "internal": internal}},
            },
        },
    )


def _plan(*resources: PlannedResource) -> ProvisioningPlan:
    return ProvisioningPlan(resources={r.address: r for r in resources}, operations=[])


def _interpret(plan: ProvisioningPlan, **kwargs):
    return interpret_provisioning_plan(plan, **kwargs)


# --- interpret: validate + serialize the plan verbatim (no re-modeling) --------


def test_interpret_serializes_full_plan_verbatim() -> None:
    plan = _plan(
        _node(
            "provision.node.web",
            "web",
            count=3,
            links=("lan",),
            source={"name": "ubuntu-22.04", "version": "1.2"},
            services=[{"name": "ssh", "port": 22, "protocol": "tcp"}],
        ),
        _network("provision.network.lan", "lan", cidr="10.9.0.0/24", internal=True),
    )
    serialized, diagnostics = _interpret(plan)
    assert [d for d in diagnostics if d.is_error] == []
    assert serialized is not None
    assert serialized["kind"] == ACES_PROVISIONING_PLAN_KIND
    assert serialized["contract_version"] == ACES_PROVISIONING_PLAN_CONTRACT_VERSION  # ADR-032-R7 transport version
    assert serialized["aces_sdl_version"]  # stamped from the installed aces-sdl
    resources = serialized["resources"]
    assert set(resources) == {"provision.node.web", "provision.network.lan"}
    # Payloads are carried verbatim -- Shifter does not re-model the plan (ADR-032-R3).
    node_spec = resources["provision.node.web"]["payload"]["spec"]["node"]
    assert node_spec["source"] == {"name": "ubuntu-22.04", "version": "1.2"}
    assert node_spec["resources"] == {"ram": 2 * 1024 * 1024 * 1024, "cpu": 2}
    props = resources["provision.network.lan"]["payload"]["spec"]["infrastructure"]["properties"]
    assert props["cidr"] == "10.9.0.0/24" and props["internal"] is True


def test_interpret_serialized_plan_is_json_safe() -> None:
    import json

    serialized, _ = _interpret(_plan(_node("provision.node.a", "a", links=())))
    # Round-trips through JSON unchanged (range_config persistence contract).
    assert json.loads(json.dumps(serialized)) == serialized


def test_aces_plan_contract_rejects_mixed_runtime_domains() -> None:
    other = PlannedResource(
        address="orchestration.step.a",
        domain=RuntimeDomain.ORCHESTRATION,
        resource_type="step",
        payload={"name": "a"},
    )
    node = _node("provision.node.a", "a")
    with pytest.raises(ValueError, match="plan domain"):
        _plan(node, other)


# --- interpret: real compiled plan --------------------------------------------


def test_interpret_consumes_real_compiled_plan() -> None:
    scenario = parse_sdl(
        'name: rt-battery-probe\nversion: "1.0.0"\nnodes:\n  web1:\n    type: vm\n    os: linux\n'
        "  dc1:\n    type: vm\n    os: windows\n"
    )
    target = create_shifter_backend_target(port=FakeDispatchPort())
    execution_plan = RuntimeManager(target).plan(scenario)
    serialized, diagnostics = _interpret(execution_plan.provisioning)
    assert [d for d in diagnostics if d.is_error] == []
    assert serialized is not None
    node_resources = [r for r in serialized["resources"].values() if r["resource_type"] == NODE_RESOURCE_TYPE]
    assert len(node_resources) == 2


def test_imageless_scenario_realizes_without_image_diagnostics() -> None:
    # #1579 / ADR-034: realizability must not fail a scenario merely for lacking
    # image references. A source-less VM is image-less (the backend supplies the
    # base OS at realization), so interpret returns a serialized plan with no
    # errors and emits no image/source diagnostic -- image count is not a
    # realizability proxy.
    scenario = parse_sdl(
        'name: imageless-realizability\nversion: "1.0.0"\nnodes:\n  host:\n    type: vm\n    os: linux\n'
    )
    target = create_shifter_backend_target(port=FakeDispatchPort())
    execution_plan = RuntimeManager(target).plan(scenario)
    serialized, diagnostics = _interpret(execution_plan.provisioning)
    assert [d for d in diagnostics if d.is_error] == []
    assert serialized is not None
    assert all("image" not in d.message.lower() for d in diagnostics)
    node_resources = [r for r in serialized["resources"].values() if r["resource_type"] == NODE_RESOURCE_TYPE]
    assert len(node_resources) == 1
    # The realized node carries no authored image `source` yet is admissible.
    assert (
        not serialized["resources"][node_resources[0]["address"]]["payload"]
        .get("spec", {})
        .get("node", {})
        .get("source")
    )


def _content_placement(address: str, *, target: str, content_type: str = "directory") -> PlannedResource:
    return PlannedResource(
        address=address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type="content-placement",
        payload={
            "name": address.rsplit(".", 1)[-1],
            "target_address": target,
            "spec": {"type": content_type, "path": "/srv/x.txt", "text": "hi"},
        },
    )


def _account_placement(address: str, *, target: str, **spec: object) -> PlannedResource:
    body = {"username": "alice", "node": "a", **spec}
    return PlannedResource(
        address=address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type="account-placement",
        payload={"name": address.rsplit(".", 1)[-1], "target_address": target, "spec": body},
    )


def _feature_binding(
    address: str,
    *,
    target: str,
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
        address=address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type="feature-binding",
        payload={
            "name": address.rsplit(".", 1)[-1],
            "feature_name": address.rsplit(".", 1)[-1],
            "node_address": target,
            "spec": {"template": template},
        },
    )


# --- capability envelope: fail closed -----------------------------------------


@pytest.mark.parametrize(
    ("plan_factory", "expected_code"),
    [
        (lambda: _plan(_node("provision.node.a", "a", os_family="macos")), "shifter-provisioner.unsupported-os-family"),
        (
            lambda: _plan(_node("provision.node.a", "a", node_type="container")),
            "shifter-provisioner.unsupported-node-type",
        ),
        (lambda: _plan(_node("provision.node.a", "a", links=("ghost",))), "shifter-provisioner.unknown-network"),
        (
            lambda: _plan(
                _content_placement("provision.content.x", target="provision.node.a", content_type="raw"),
                _node("provision.node.a", "a"),
            ),
            "shifter-provisioner.unsupported-content-type",
        ),
        (
            lambda: _plan(_content_placement("provision.content.x", target="provision.node.ghost")),
            "shifter-provisioner.unbound-placement",
        ),
        (
            lambda: _plan(_network("provision.network.lan", "lan", cidr="2001:db8:1234::/48")),
            "shifter-provisioner.unsupported-network-address-family",
        ),
    ],
)
def test_out_of_envelope_terms_fail_closed(plan_factory, expected_code: str) -> None:
    serialized, diagnostics = _interpret(plan_factory())
    assert serialized is None
    assert any(d.is_error and d.code == expected_code for d in diagnostics)


def test_aces_plan_contract_rejects_unknown_provisioning_resource_type() -> None:
    resource = PlannedResource(
        address="provision.blob.x",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="blob",
        payload={"name": "x"},
    )
    with pytest.raises(ValueError, match="resource_type"):
        _plan(resource)


def test_acls_are_in_envelope_and_carried_verbatim() -> None:
    # supports_acls is now True: the backend realizes authored node ACLs as
    # firewall rules, so an ACL-bearing plan is accepted (not rejected) and the
    # authored acls survive verbatim for the provisioner to realize.
    plan = _plan(
        _node(
            "provision.node.a",
            "a",
            links=("lan",),
            acls=[{"action": "allow", "direction": "in", "protocol": "tcp", "ports": [22], "from_net": "lan"}],
        ),
        _network("provision.network.lan", "lan"),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is not None
    assert not any(d.code == "shifter-provisioner.acls-unsupported" for d in diagnostics)
    node_payload = serialized["resources"]["provision.node.a"]["payload"]
    assert node_payload["spec"]["infrastructure"]["acls"][0]["action"] == "allow"


def test_composition_placements_accepted_and_serialized() -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _content_placement("provision.content.doc", target="provision.node.a"),
        _account_placement("provision.account.alice", target="provision.node.a", groups=["ops"]),
        _feature_binding("provision.feature.web", target="provision.node.a"),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is not None
    assert not any(d.is_error for d in diagnostics)
    types = {r["resource_type"] for r in serialized["resources"].values()}
    assert {"content-placement", "account-placement", "feature-binding"} <= types


def test_accounts_unsupported_fails_closed() -> None:
    caps = ProvisionerCapabilities(
        name="noacct", supported_node_types=frozenset({"vm"}), supported_os_families=frozenset({"linux"})
    )
    plan = _plan(_node("provision.node.a", "a"), _account_placement("provision.account.a", target="provision.node.a"))
    serialized, diagnostics = _interpret(plan, capabilities=caps)
    assert serialized is None
    assert any(d.code == "shifter-provisioner.accounts-unsupported" for d in diagnostics)


def test_account_feature_outside_envelope_fails_closed() -> None:
    caps = ProvisionerCapabilities(
        name="restricted",
        supported_node_types=frozenset({"vm"}),
        supported_os_families=frozenset({"linux"}),
        supported_account_features=frozenset({"groups"}),
        supports_accounts=True,
    )
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", mail="a@b.c"),
    )
    serialized, diagnostics = _interpret(plan, capabilities=caps)
    assert serialized is None
    assert any(d.code == "shifter-provisioner.unsupported-account-feature" for d in diagnostics)


# --- honest realizability ledger (#1563): narrowed envelope + independent evidence gate ---


@pytest.mark.parametrize(
    ("spec", "feature", "authored_value"),
    [
        ({"mail": "alice@example.com"}, "mail", "alice@example.com"),
    ],
)
def test_dropped_account_features_fail_closed(spec: dict, feature: str, authored_value: str) -> None:
    # mail remains absent from the honest manifest until genuine realization exists.
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", **spec),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is None
    assert any(
        d.is_error and d.code == "shifter-provisioner.unsupported-account-feature" and feature in d.message
        for d in diagnostics
    )
    # the authored value never leaks into a diagnostic (governed feature term only)
    assert all(authored_value not in d.message for d in diagnostics)


def test_spn_requires_an_explicit_supported_domain_binding() -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", spn="host/dc1.example.com"),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.account-spn-domain-required" for d in diagnostics)
    assert all("host/dc1.example.com" not in d.message for d in diagnostics)


@pytest.mark.parametrize("auth_method", ["kerberos", "PASSWORD", "public-key"])
def test_auth_method_value_outside_backend_policy_fails_closed(auth_method: str) -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", auth_method=auth_method),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.unsupported-account-auth-method" for d in diagnostics)
    assert all(auth_method not in d.message for d in diagnostics)


@pytest.mark.parametrize("auth_method", [None, 1, [], {}])
def test_explicit_malformed_auth_method_is_not_defaulted(auth_method: object) -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", auth_method=auth_method),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.invalid-account-auth-method" for d in diagnostics)


@pytest.mark.parametrize("password_strength", [None, 1, [], {}])
def test_explicit_malformed_password_strength_is_not_defaulted(password_strength: object) -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", password_strength=password_strength),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.invalid-password-strength" for d in diagnostics)


@pytest.mark.parametrize("username", ["aces", "ACES"])
def test_provisioner_management_username_fails_before_dispatch(username: str) -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.management", target="provision.node.a", username=username),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.reserved-account-username" for d in diagnostics)
    assert all(username not in d.message for d in diagnostics)


def test_none_password_strength_fails_closed_without_blank_password_semantics() -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement(
            "provision.account.a",
            target="provision.node.a",
            auth_method="password",
            password_strength="none",
        ),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is None
    assert any(d.code == "shifter-provisioner.unsupported-password-strength" for d in diagnostics)


def test_disabled_account_allows_explicit_no_password_semantics() -> None:
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement(
            "provision.account.a",
            target="provision.node.a",
            auth_method="password",
            password_strength="none",
            disabled=True,
        ),
    )

    serialized, diagnostics = _interpret(plan)

    assert serialized is not None
    assert not any(d.code == "shifter-provisioner.unsupported-password-strength" for d in diagnostics)


@pytest.mark.parametrize(
    "spec",
    [
        {"groups": ["ops"]},
        {"shell": "/bin/bash"},
        {"home": "/home/alice"},
        {"disabled": True},
        {"auth_method": "publickey"},
    ],
)
def test_retained_account_features_pass_declaration_and_evidence(spec: dict) -> None:
    # Every retained feature must clear BOTH the manifest declaration and the independent
    # evidence ledger (#1563) -- the two hand-maintained frozensets must agree for every
    # declared term, not just "groups". If a future edit drifts one from the other, a real
    # range authoring that feature would fail closed; this positive path is the guard.
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", **spec),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is not None
    assert not any(
        d.code
        in {"shifter-provisioner.unsupported-account-feature", "shifter-provisioner.account-feature-not-realized"}
        for d in diagnostics
    )


@pytest.mark.parametrize("content_type", ["dataset"])
def test_dropped_content_types_fail_closed(content_type: str) -> None:
    # #1564 re-declares file + directory (genuine, digest-verified delivery); dataset
    # stays out (no deterministic materializer + readback) and fails closed.
    plan = _plan(
        _node("provision.node.a", "a"),
        _content_placement("provision.content.x", target="provision.node.a", content_type=content_type),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is None
    assert any(d.is_error and d.code == "shifter-provisioner.unsupported-content-type" for d in diagnostics)


@pytest.mark.parametrize("content_type", ["file", "directory"])
def test_declared_content_types_are_admitted(content_type: str) -> None:
    # #1564: file + directory are declared capabilities; a well-formed placement of
    # either type must NOT raise an unsupported-content-type diagnostic.
    plan = _plan(
        _node("provision.node.a", "a"),
        _content_placement("provision.content.x", target="provision.node.a", content_type=content_type),
    )
    _serialized, diagnostics = _interpret(plan)
    assert not any(d.code == "shifter-provisioner.unsupported-content-type" for d in diagnostics)


def _mail_overclaimed_capabilities() -> ProvisionerCapabilities:
    # Manifest over-claim: mail re-declared without genuine realization evidence.
    return ProvisionerCapabilities(
        name="overclaimed",
        supported_node_types=frozenset({"vm", "switch"}),
        supported_os_families=frozenset({"linux", "windows"}),
        supported_account_features=frozenset({"groups", "mail"}),
        supports_accounts=True,
    )


def test_evidence_policy_is_independent_of_manifest_declaration() -> None:
    # Widening the manifest must NOT widen realization: the independent evidence
    # gate rejects mail even though the declaration now allows it.
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", mail="alice@example.com"),
    )
    serialized, diagnostics = _interpret(plan, capabilities=_mail_overclaimed_capabilities())
    assert serialized is None
    # the declaration check passes (mail IS in the over-claimed envelope) ...
    assert not any(d.code == "shifter-provisioner.unsupported-account-feature" for d in diagnostics)
    # ... but the independent evidence gate fails closed.
    assert any(
        d.is_error and d.code == "shifter-provisioner.account-feature-not-realized" and "mail" in d.message
        for d in diagnostics
    )


def test_declared_but_unrealized_account_feature_fails_validate_and_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    # The same evidence gate serves validate() and apply() on the one pure path,
    # and apply() never dispatches an unrealized-feature plan.
    monkeypatch.setattr("shared.aces.runtime_target.SHIFTER_PROVISIONER_CAPABILITIES", _mail_overclaimed_capabilities())
    port = FakeDispatchPort()
    plan = _plan(
        _node("provision.node.a", "a"),
        _account_placement("provision.account.a", target="provision.node.a", mail="alice@example.com"),
    )
    provisioner = ShifterProvisioner(port)
    assert any(d.code == "shifter-provisioner.account-feature-not-realized" for d in provisioner.validate(plan))
    result = provisioner.apply(plan, RuntimeSnapshot())
    assert result.success is False
    assert port.plans == []  # fail closed: no dispatch
    assert any(d.code == "shifter-provisioner.account-feature-not-realized" for d in result.diagnostics)
    assert all("alice@example.com" not in d.message for d in result.diagnostics)


def _account_op(address: str, *, action: ChangeAction, target: str = "provision.node.a", **spec: object) -> ProvisionOp:
    body = {"username": "alice", "node": "a", **spec}
    return ProvisionOp(
        action=action,
        address=address,
        resource_type="account-placement",
        payload={"name": address.rsplit(".", 1)[-1], "target_address": target, "spec": body},
    )


def _plan_ops(resources: list[PlannedResource], operations: list[ProvisionOp]) -> ProvisioningPlan:
    return ProvisioningPlan(resources={r.address: r for r in resources}, operations=list(operations))


def test_operation_only_account_overclaim_fails_and_does_not_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # An over-claimed feature carried ONLY by a materializing operation (no matching
    # resource) must still fail closed before dispatch -- an operation-only payload
    # cannot bypass the realization ledger.
    monkeypatch.setattr("shared.aces.runtime_target.SHIFTER_PROVISIONER_CAPABILITIES", _mail_overclaimed_capabilities())
    port = FakeDispatchPort()
    plan = _plan_ops(
        [_node("provision.node.a", "a")],
        [_account_op("provision.account.op", action=ChangeAction.CREATE, mail="alice@example.com")],
    )
    provisioner = ShifterProvisioner(port)
    assert any(
        d.code == "shifter-provisioner.account-feature-not-realized" and d.address == "provision.account.op"
        for d in provisioner.validate(plan)
    )
    result = provisioner.apply(plan, RuntimeSnapshot())
    assert result.success is False
    assert port.plans == []  # fail closed: no dispatch


def test_delete_account_operation_is_exempt() -> None:
    # A DELETE operation removes an account and does not materialize its historical
    # features, so an over-claimed feature on a DELETE op is not rejected.
    plan = _plan_ops(
        [_node("provision.node.a", "a")],
        [_account_op("provision.account.gone", action=ChangeAction.DELETE, spn="host/dc1.example.com")],
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is not None
    assert not any(
        d.code
        in {"shifter-provisioner.account-feature-not-realized", "shifter-provisioner.unsupported-account-feature"}
        for d in diagnostics
    )


def test_account_resource_and_create_operation_do_not_double_report(monkeypatch: pytest.MonkeyPatch) -> None:
    # A resource and its own CREATE operation for the same over-claimed feature yield
    # a single diagnostic, not two.
    monkeypatch.setattr("shared.aces.runtime_target.SHIFTER_PROVISIONER_CAPABILITIES", _mail_overclaimed_capabilities())
    plan = _plan_ops(
        [
            _node("provision.node.a", "a"),
            _account_placement("provision.account.a", target="provision.node.a", mail="alice@example.com"),
        ],
        [_account_op("provision.account.a", action=ChangeAction.CREATE, mail="alice@example.com")],
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is None
    not_realized = [d for d in diagnostics if d.code == "shifter-provisioner.account-feature-not-realized"]
    assert len(not_realized) == 1  # deduplicated across the resource and operation views


def test_node_budget_enforced() -> None:
    capped = ProvisionerCapabilities(
        name="capped",
        supported_node_types=frozenset({"vm"}),
        supported_os_families=frozenset({"linux", "windows"}),
        max_total_nodes=1,
    )
    serialized, diagnostics = _interpret(_plan(_node("provision.node.a", "a", count=5)), capabilities=capped)
    assert serialized is None
    assert any(d.code == "shifter-provisioner.node-budget-exceeded" for d in diagnostics)


def test_non_mapping_payload_rejected() -> None:
    bad = PlannedResource(
        address="provision.node.a", domain=RuntimeDomain.PROVISIONING, resource_type=NODE_RESOURCE_TYPE, payload=[]
    )
    serialized, diagnostics = _interpret(_plan(bad))
    assert serialized is None
    assert any(d.code == "shifter-provisioner.invalid-payload" for d in diagnostics)


def test_all_diagnostics_are_bounded_and_sanitized() -> None:
    plans = [
        _plan(_node("provision.node.a", "a", os_family="freebsd")),
        _plan(_node("provision.node.a", "a", node_type="container")),
        _plan(_node("provision.node.a", "a", links=("ghost",))),
    ]
    for plan in plans:
        _, diagnostics = _interpret(plan)
        for diagnostic in diagnostics:
            assert "\n" not in diagnostic.message
            assert len(diagnostic.message) <= 480
            lowered = diagnostic.message.lower()
            assert not any(marker in lowered for marker in _FORBIDDEN_DIAGNOSTIC_SUBSTRINGS)


# --- apply / dispatch ----------------------------------------------------------


def test_apply_dispatches_serialized_plan_and_reports_snapshot() -> None:
    port = FakeDispatchPort()
    plan = _plan(_node("provision.node.web", "web", links=("lan",)), _network("provision.network.lan", "lan"))
    result = ShifterProvisioner(port).apply(plan, RuntimeSnapshot())
    assert result.success is True
    assert set(result.changed_addresses) == {"provision.node.web", "provision.network.lan"}
    provisioning_entries = [e for e in result.snapshot.entries.values() if e.domain == RuntimeDomain.PROVISIONING]
    assert len(provisioning_entries) == 2
    assert all(entry.payload["request_id"] == REQUEST_ID for entry in provisioning_entries)
    assert len(port.plans) == 1
    assert port.plans[0]["kind"] == ACES_PROVISIONING_PLAN_KIND


def test_apply_does_not_dispatch_on_invalid_plan() -> None:
    port = FakeDispatchPort()
    result = ShifterProvisioner(port).apply(_plan(_node("provision.node.a", "a", os_family="macos")), RuntimeSnapshot())
    assert result.success is False
    assert port.plans == []


def test_apply_wraps_dispatch_failure_as_diagnostic() -> None:
    port = FakeDispatchPort(raises=RuntimeError("boom"))
    plan = _plan(_node("provision.node.web", "web"))
    result = ShifterProvisioner(port).apply(plan, RuntimeSnapshot())
    assert result.success is False
    assert any(d.code == "shifter-provisioner.dispatch-failed" for d in result.diagnostics)


def test_apply_and_validate_reject_non_plan() -> None:
    provisioner = ShifterProvisioner(FakeDispatchPort())
    assert provisioner.validate("nope")[0].code == "shifter-provisioner.invalid-plan"
    result = provisioner.apply("nope", RuntimeSnapshot())
    assert result.success is False


def test_validate_clean_plan_has_no_errors() -> None:
    plan = _plan(_node("provision.node.web", "web", links=("lan",)), _network("provision.network.lan", "lan"))
    assert [d for d in ShifterProvisioner(FakeDispatchPort()).validate(plan) if d.is_error] == []


# --- registration / target shape ----------------------------------------------


def test_create_target_is_provisioning_only() -> None:
    target = create_shifter_backend_target(port=FakeDispatchPort())
    assert target.manifest.has_orchestrator is False
    assert target.manifest.has_evaluator is False
    assert target.manifest.has_participant_runtime is False
    assert isinstance(target.provisioner, ShifterProvisioner)


def test_components_match_manifest_shape() -> None:
    manifest = create_shifter_backend_manifest()
    components = create_shifter_backend_components(manifest=manifest, port=FakeDispatchPort())
    assert isinstance(components.provisioner, ShifterProvisioner)
    assert components.orchestrator is None
    assert components.evaluator is None


def test_register_shifter_backend() -> None:
    registry = BackendRegistry()
    register_shifter_backend(registry)
    assert registry.is_registered(SHIFTER_BACKEND_NAME)
