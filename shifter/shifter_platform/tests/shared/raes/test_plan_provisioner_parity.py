"""Producer -> consumer contract test for the serialized RAES ProvisioningPlan.

Per ADR-032 Shifter rides the RAES contract: the platform serializes the compiled
ProvisioningPlan (``serialize_provisioning_plan``) and the provisioner reads it via
``shifter/engine/provisioner/raes_plan.py`` (loaded standalone, since it is
pure-stdlib). This test drives that boundary end to end using **only public RAES
contract types** (``raes_contracts``) and the Shifter producer, and asserts the
consumer extracts the expected Shifter-owned values and enforces the ADR-032-R7
transport version contract.

The contract is asserted against public APIs and Shifter-owned fixtures only -- no
private reference-backend helpers (ADR-032-R7 / issue #1522). This guards the
*consumer's own* extraction against regression (editing ``raes_plan.py``'s accessors
breaks these expectations). It is deliberately not a live differential oracle against
the reference backend's *private* accessors -- those are not a public contract
(ADR-032-R7). The consumer accepts the exact pinned ``raes==3.5.0`` producer
and must be re-validated with this fixture and the RAES conformance gate before
that exact version changes.

Exception (ADR-032-R8 / issue #1562): ``TestServiceExtractionParity`` is a bounded,
services-only differential against the reference backend's *public* pure interpreter
(``raes_backend_libvirt.realization.interpret_provisioning_plan``) for *valid, named*
tcp/udp services. It uses no private accessors and is a best-effort, test-only oracle
(skipped if the reference backend is not installed), so it does not make the reference
backend a runtime compatibility contract. Shifter's stricter, fail-closed handling of
unnamed services and unknown protocols (which the reference silently drops / coerces to
TCP) is a deliberate divergence, so the differential intentionally covers only the
valid overlap where both must agree.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest
from raes.parser import parse_sdl
from raes_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from raes_processor.compiler import compile_runtime_model
from raes_processor.planner import plan as compile_plan

from shared.raes.contracts import RAES_PROVISIONING_PLAN_CONTRACT_VERSION
from shared.raes.manifest import create_shifter_backend_manifest
from shared.raes.runtime_target import serialize_provisioning_plan

_PROVISIONER_READER = Path(__file__).resolve().parents[4] / "engine" / "provisioner" / "raes_plan.py"
_SHIFTER_PLATFORM_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def _load_provisioner_reader():
    # raes_plan imports its sibling raes_composition, so the provisioner dir must be
    # importable when the reader is loaded standalone.
    provisioner_dir = str(_PROVISIONER_READER.parent)
    if provisioner_dir not in sys.path:
        sys.path.insert(0, provisioner_dir)
    spec = importlib.util.spec_from_file_location("raes_plan_provisioner", _PROVISIONER_READER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _exact_dependency_pin(package: str) -> str:
    """Return one exact runtime dependency pin from platform metadata."""
    data = tomllib.loads(_SHIFTER_PLATFORM_PYPROJECT.read_text())
    for dep in data["project"]["dependencies"]:
        normalized = dep.replace(" ", "")
        if normalized.startswith(f"{package}=="):
            return normalized.split("==", 1)[1].split(";", 1)[0].strip()
    raise AssertionError(f"exact {package} pin not found in shifter_platform/pyproject.toml")


@pytest.fixture(scope="module")
def reader():
    return _load_provisioner_reader()


def _node_payload() -> dict:
    return {
        "name": "web",
        "os_family": "linux",
        "count": 3,
        "spec": {
            "node": {"source": {"name": "ubuntu-22.04", "version": "1.2"}, "resources": {"ram": 2147483648, "cpu": 4}},
            "infrastructure": {"networks": ["provision.network.lan"]},
        },
    }


def _plan() -> ProvisioningPlan:
    node = PlannedResource(
        address="provision.node.web",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload=_node_payload(),
    )
    network = PlannedResource(
        address="provision.network.lan",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="network",
        payload={"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
    )
    return ProvisioningPlan(resources={node.address: node, network.address: network})


def _domain_plan() -> ProvisioningPlan:
    scenario = parse_sdl(
        """
        name: domain-parity-probe
        nodes:
          lan: {type: switch}
          dc: {type: compute, os: windows}
          member: {type: compute, os: windows}
        accounts:
          domain-admin: {username: Administrator, node: dc}
          local-operator: {username: local-operator, node: member}
          web-service:
            username: svc-web
            node: member
            auth_method: password
            spn: HTTP/member.corp.example
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
          dc: {count: 1, links: [lan]}
          member: {count: 1, links: [lan]}
        """
    )
    return compile_plan(
        compile_runtime_model(scenario),
        create_shifter_backend_manifest(),
    ).provisioning


class TestProvisionerReaderContract:
    def test_kind_constant_matches_serializer(self, reader):
        from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND

        assert reader.RAES_PROVISIONING_PLAN_KIND == RAES_PROVISIONING_PLAN_KIND

    def test_contract_version_round_trips(self, reader):
        # ADR-032-R7: the producer stamp is a version the consumer accepts; the two
        # contract-version constants stay in lockstep (the consumer ships without
        # ``shared`` so this parity test is the drift guard).
        assert reader.RAES_PROVISIONING_PLAN_CONTRACT_VERSION == RAES_PROVISIONING_PLAN_CONTRACT_VERSION
        assert RAES_PROVISIONING_PLAN_CONTRACT_VERSION in reader.SUPPORTED_CONTRACT_VERSIONS
        # A plan serialized by the producer parses cleanly through the consumer.
        parsed = reader.parse_plan(serialize_provisioning_plan(_plan()))
        assert parsed.raes_version  # the installed raes version, validated

    def test_account_auth_policy_matches_separate_provisioner_consumer(self, reader):
        from shared.raes.composition_envelope import SUPPORTED_ACCOUNT_AUTH_METHODS

        assert reader.SUPPORTED_ACCOUNT_AUTH_METHODS == SUPPORTED_ACCOUNT_AUTH_METHODS

    def test_supported_raes_release_agrees_with_pin_and_lock(self, reader):
        assert reader.SUPPORTED_RAES_VERSION == "3.5.0"
        assert importlib.metadata.version("raes") == _exact_dependency_pin("raes")
        assert importlib.metadata.version("raes") == reader.SUPPORTED_RAES_VERSION

    def test_environment_pack_and_raes_release_pair_is_exact(self):
        assert importlib.metadata.version("raes") == "3.5.0"
        assert importlib.metadata.version("raes") == _exact_dependency_pin("raes")
        assert importlib.metadata.version("raes-env-packs") == "5.2.0"
        assert importlib.metadata.version("raes-env-packs") == _exact_dependency_pin("raes-env-packs")
        requirements = importlib.metadata.requires("raes-env-packs") or []
        normalized = {requirement.replace(" ", "").lower() for requirement in requirements}
        assert "raes==3.5.0" in normalized

    def test_extraction_matches_expected_shifter_fixture(self, reader):
        parsed = reader.parse_plan(serialize_provisioning_plan(_plan()))

        node = next(n for n in parsed.nodes if n.address == "provision.node.web")
        # Authored intent extracted verbatim (Shifter-owned expected values).
        assert node.image is not None
        assert node.image.name == "ubuntu-22.04"
        assert node.image.version == "1.2"
        assert node.ram_mib == 2048  # 2 GiB bytes -> MiB
        assert node.vcpus == 4
        assert node.os_family == "linux"
        assert node.network_addresses == ("provision.network.lan",)

        network = next(n for n in parsed.networks if n.address == "provision.network.lan")
        assert network.cidr == "10.9.0.0/24"

    def test_raes_35_static_address_shape_round_trips_to_the_consumer(self, reader):
        node = PlannedResource(
            address="provision.node.web",
            domain=RuntimeDomain.PROVISIONING,
            resource_type="node",
            payload={
                "name": "web",
                "os_family": "linux",
                "count": 1,
                "spec": {
                    "node": {"source": "ubuntu"},
                    "infrastructure": {
                        "links": ["lan"],
                        "properties": [{"lan": "10.50.0.10"}],
                    },
                },
            },
        )
        network = PlannedResource(
            address="provision.network.lan",
            domain=RuntimeDomain.PROVISIONING,
            resource_type="network",
            payload={"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.50.0.0/24"}}}},
        )

        parsed = reader.parse_plan(
            serialize_provisioning_plan(ProvisioningPlan(resources={node.address: node, network.address: network}))
        )

        assert parsed.nodes[0].network_ip_assignments == (("provision.network.lan", "10.50.0.10"),)

    def test_public_domain_topology_round_trips_to_the_separate_consumer(self, reader):
        parsed = reader.parse_plan(serialize_provisioning_plan(_domain_plan()))

        assert parsed.domains == (
            reader.RaesPlanDomain(
                domain_id="corp",
                profile="active_directory",
                dns_name="corp.example",
                netbios_name="CORP",
                authority_account_address="provision.account.domain-admin",
                controller_addresses=("provision.node.dc",),
                member_addresses=("provision.node.member",),
            ),
        )
        member = next(node for node in parsed.nodes if node.address == "provision.node.member")
        assert member.domain_id == "corp"
        assert member.domain_role == "member"
        assert member.controller_addresses == ("provision.node.dc",)
        assert "provision.node.dc" in member.ordering_dependencies

        service_account = next(account for account in parsed.accounts if account.username == "svc-web")
        assert service_account.address == "provision.account.web-service"
        assert service_account.domain_ref == "corp"
        assert service_account.domain_id == "corp"
        assert service_account.spn == "HTTP/member.corp.example"

        local_account = next(account for account in parsed.accounts if account.username == "local-operator")
        assert local_account.domain_id is None
        assert local_account.domain_ref is None

    def test_acl_extraction_normalizes_to_expected(self, reader):
        raw_acls = [
            {
                "name": "ssh",
                "action": "allow",
                "direction": "in",
                "protocol": "TCP",
                "ports": [22],
                "from_net": "provision.network.lan",
            }
        ]
        node = PlannedResource(
            address="provision.node.web",
            domain=RuntimeDomain.PROVISIONING,
            resource_type="node",
            payload={"name": "web", "os_family": "linux", "spec": {"infrastructure": {"acls": raw_acls}}},
        )
        # Declare the network the ACL endpoint references so parse resolves it (ADR-032-R7).
        network = PlannedResource(
            address="provision.network.lan",
            domain=RuntimeDomain.PROVISIONING,
            resource_type="network",
            payload={"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
        )
        serialized = serialize_provisioning_plan(
            ProvisioningPlan(resources={node.address: node, network.address: network})
        )
        acl = reader.parse_plan(serialized).nodes[0].acls[0]
        # Shifter-owned normalization: allow->accept, TCP->tcp; endpoint kept as ref
        # (resolved to a concrete CIDR at realization, fail-closed).
        assert (acl.action, acl.direction, acl.protocol, acl.ports) == ("accept", "in", "tcp", (22,))
        assert acl.from_net == "provision.network.lan"
        assert acl.to_net is None


def _plan_with_services(services: list[dict]) -> ProvisioningPlan:
    node = PlannedResource(
        address="provision.node.web",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="node",
        payload={
            "name": "web",
            "node_type": "compute",
            "os_family": "linux",
            "spec": {
                "node": {"type": "compute", "os": "linux", "services": services},
                "infrastructure": {"networks": ["provision.network.lan"]},
            },
        },
    )
    network = PlannedResource(
        address="provision.network.lan",
        domain=RuntimeDomain.PROVISIONING,
        resource_type="network",
        payload={"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
    )
    return ProvisioningPlan(resources={node.address: node, network.address: network})


class TestServiceExtractionParity:
    """Services-only differential vs the reference backend's PUBLIC interpreter (ADR-032-R8)."""

    def test_valid_named_services_match_public_libvirt_reference(self, reader):
        # Test-only oracle (public API only, no private accessors); skipped if the
        # reference backend is not installed so it never becomes a runtime contract.
        libvirt = pytest.importorskip("raes_backend_libvirt.realization")
        services = [
            {"name": "http", "port": 80, "protocol": "tcp"},
            {"name": "dns", "port": 53, "protocol": "udp"},
        ]
        plan = _plan_with_services(services)

        reference = libvirt.interpret_provisioning_plan(plan)
        reference_domain = next(domain for domain in reference.domains if domain.address == "provision.node.web")
        reference_tuples = {(svc.protocol, svc.port, svc.name) for svc in reference_domain.services}

        parsed = reader.parse_plan(serialize_provisioning_plan(plan))
        shifter_node = next(node for node in parsed.nodes if node.address == "provision.node.web")
        shifter_tuples = {(svc.protocol, svc.port, svc.name) for svc in shifter_node.services}

        assert shifter_tuples == reference_tuples == {("tcp", 80, "http"), ("udp", 53, "dns")}

    def test_shifter_is_stricter_than_reference_on_unknown_protocol(self, reader):
        # The reference coerces an unknown protocol to TCP (fail-open); Shifter rejects
        # it at its separate trust boundary (fail-closed) -- a deliberate divergence.
        serialized = serialize_provisioning_plan(_plan_with_services([{"name": "x", "port": 80, "protocol": "sctp"}]))
        with pytest.raises(reader.RaesPlanError, match="protocol"):
            reader.parse_plan(serialized)


@pytest.mark.parametrize("name", ["web", None])
def test_released_public_accessors_agree_with_standalone_reader(reader, name):
    from raes_contracts.planning import (
        planned_infrastructure_spec,
        planned_node_resources,
        planned_node_source,
        planned_node_spec,
        planned_resource_name,
    )

    payload = _node_payload()
    if name is None:
        payload.pop("name")
    resource = PlannedResource("provision.node.web", RuntimeDomain.PROVISIONING, "node", payload)
    assert reader._resource_name(resource.address, payload) == planned_resource_name(resource)
    assert reader._node_spec(payload) == planned_node_spec(resource)
    assert reader._infrastructure_spec(payload) == planned_infrastructure_spec(resource)
    source = planned_node_source(resource)
    image = reader._image(payload)
    assert (image.name, image.version) == (source["name"], source["version"])
    sizing = planned_node_resources(resource)
    assert reader._memory_mib(payload) == sizing["ram"] // (1024 * 1024)
    assert reader._vcpus(payload) == sizing["cpu"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", False),
        ("source", {"name": 3}),
        ("resources", []),
        ("resources", {"cpu": "2"}),
        ("resources", {"ram": False}),
    ],
)
def test_malformed_present_fields_never_become_backend_defaults(reader, field, value):
    payload = _node_payload()
    payload["spec"]["node"][field] = value
    payload["spec"]["infrastructure"] = {}
    resource = PlannedResource("provision.node.web", RuntimeDomain.PROVISIONING, "node", payload)
    with pytest.raises(reader.RaesPlanError):
        reader.parse_plan(serialize_provisioning_plan(ProvisioningPlan(resources={resource.address: resource})))
