"""Tests for the provisioner-side serialized-ACES-plan reader (ADR-031, ADR-032).

The reader consumes the serialized ACES ProvisioningPlan persisted in
range_config and extracts realization intent via accessors mirroring the
reference ACES backend. These tests drive it directly with serialized-plan dicts;
a platform-side drift test compares its extraction against aces_backend_libvirt.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_plan import (
    ACES_PROVISIONING_PLAN_KIND,
    AcesPlan,
    AcesPlanError,
    parse_plan,
)


def _resource(address: str, resource_type: str, payload: dict) -> dict:
    return {
        "address": address,
        "domain": "provisioning",
        "resource_type": resource_type,
        "payload": payload,
        "ordering_dependencies": [],
        "refresh_dependencies": [],
    }


def _serialized(*resources: dict, version: str = "0.19.1") -> dict:
    return {
        "kind": ACES_PROVISIONING_PLAN_KIND,
        "aces_sdl_version": version,
        "resources": {r["address"]: r for r in resources},
    }


def _node_payload(**node_spec) -> dict:
    return {
        "name": "attacker",
        "os_family": "linux",
        "count": 2,
        "spec": {
            "node": {
                "source": {"name": "kali", "version": "2024.1"},
                "resources": {"ram": 2147483648, "cpu": 2},
                **node_spec,
            },
            "infrastructure": {"networks": ["net.default"]},
        },
    }


class TestParseValid:
    def test_extracts_node_and_network(self):
        plan = _serialized(
            _resource("node.attacker", "node", _node_payload()),
            _resource(
                "net.default",
                "network",
                {
                    "name": "default",
                    "spec": {
                        "infrastructure": {
                            "properties": {"cidr": "10.0.0.0/24", "gateway": "10.0.0.1", "internal": True}
                        }
                    },
                },
            ),
        )
        parsed = parse_plan(plan)
        assert isinstance(parsed, AcesPlan)
        assert parsed.aces_sdl_version == "0.19.1"

        node = parsed.nodes[0]
        assert node.address == "node.attacker"
        assert node.os_family == "linux"
        assert node.count == 2
        assert node.ram_mib == 2048  # 2 GiB bytes -> MiB
        assert node.vcpus == 2
        assert node.image is not None and node.image.name == "kali" and node.image.version == "2024.1"
        assert node.network_addresses == ("net.default",)  # resolved via lookup

        net = parsed.networks[0]
        assert net.cidr == "10.0.0.0/24" and net.gateway == "10.0.0.1" and net.internal is True

    def test_os_family_falls_back_to_spec_node_os(self):
        payload = {"spec": {"node": {"os": "windows"}}}
        parsed = parse_plan(_serialized(_resource("node.dc", "node", payload)))
        assert parsed.nodes[0].os_family == "windows"

    def test_small_ram_treated_as_mib(self):
        payload = {"os_family": "linux", "spec": {"node": {"resources": {"ram": 512}}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].ram_mib == 512

    def test_bare_string_source(self):
        payload = {"os_family": "windows", "spec": {"node": {"source": "win2022-template"}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].image is not None
        assert parsed.nodes[0].image.name == "win2022-template" and parsed.nodes[0].image.version is None

    def test_absent_sizing_and_image_are_none(self):
        payload = {"os_family": "linux", "spec": {"node": {}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        node = parsed.nodes[0]
        assert node.ram_mib is None and node.vcpus is None and node.image is None
        assert node.count == 1  # default

    def test_unresolvable_network_ref_dropped(self):
        payload = {"os_family": "linux", "spec": {"infrastructure": {"networks": ["ghost"]}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].network_addresses == ()


class TestSelfDiscrimination:
    def test_rejects_none(self):
        with pytest.raises(AcesPlanError):
            parse_plan(None)

    def test_rejects_wrong_kind(self):
        plan = _serialized(_resource("node.a", "node", {"os_family": "linux"}))
        plan["kind"] = "something-else"
        with pytest.raises(AcesPlanError):
            parse_plan(plan)

    def test_rejects_cyberscript_envelope(self):
        envelope = {"spec_schema": "range_spec", "spec_version": "1", "payload": {"scenario_id": "basic-attack"}}
        with pytest.raises(AcesPlanError):
            parse_plan(envelope)
