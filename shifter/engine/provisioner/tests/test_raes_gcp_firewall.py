"""Tests for authored-ACL -> GCE firewall realization (ADR-031, ADR-032).

Security-critical translation: verifies direction/action/protocol/ports mapping,
fail-closed endpoint resolution (omitted = any; unresolvable = raise, never a
broad allow), author-order priority, and the per-node target tag. Precedence vs
the base management plane is documented in raes_gcp_firewall.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raes_gcp_firewall import (
    RaesGceFirewallError,
    acl_cidr_lookup,
    build_acl_firewalls,
    build_service_firewalls,
    node_tag,
)
from raes_plan import RaesPlanAcl, RaesPlanNetwork, RaesPlanNode, RaesPlanServicePort


def _node(acls: tuple[RaesPlanAcl, ...], *, address: str = "node.web") -> RaesPlanNode:
    return RaesPlanNode(
        address=address,
        name=address.rsplit(".", 1)[-1],
        os_family="linux",
        count=1,
        network_addresses=("net.lan",),
        acls=acls,
    )


_LOOKUP = {"net.lan": "10.9.0.0/24", "lan": "10.9.0.0/24", "net.dmz": "10.9.1.0/24"}


def _acl(**kw) -> RaesPlanAcl:
    base = {
        "name": "r",
        "action": "accept",
        "direction": "in",
        "protocol": "all",
        "ports": (),
        "from_net": None,
        "to_net": None,
    }
    base.update(kw)
    return RaesPlanAcl(**base)


class TestAclCidrLookup:
    def test_keys_networks_by_address_name_and_leaf(self):
        networks = (RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24"),)
        lookup = acl_cidr_lookup(networks)
        assert lookup == {"net.lan": "10.9.0.0/24", "lan": "10.9.0.0/24"}

    def test_networks_without_cidr_are_skipped(self):
        networks = (RaesPlanNetwork(address="net.lan", name="lan", cidr=None),)
        assert acl_cidr_lookup(networks) == {}


class TestDirectionAndAction:
    def test_allow_inbound_tcp_port(self):
        acl = _acl(action="accept", direction="in", protocol="tcp", ports=(22,), from_net="net.dmz")
        firewalls = build_acl_firewalls(7, _node((acl,)), node_tag(7, "node.web"), _LOOKUP)
        assert len(firewalls) == 1
        fw = firewalls[0]
        assert fw["direction"] == "INGRESS"
        assert fw["allowed"] == [{"IPProtocol": "tcp", "ports": ["22"]}]
        assert fw["source_ranges"] == ["10.9.1.0/24"]
        assert fw["target_tags"] == [node_tag(7, "node.web")]
        assert fw["priority"] == 1000

    def test_deny_outbound_uses_denied_and_destination_ranges(self):
        acl = _acl(action="drop", direction="out", protocol="all", to_net="net.dmz")
        fw = build_acl_firewalls(7, _node((acl,)), node_tag(7, "node.web"), _LOOKUP)[0]
        assert fw["direction"] == "EGRESS"
        assert fw["denied"] == [{"IPProtocol": "all"}]
        assert fw["destination_ranges"] == ["10.9.1.0/24"]
        assert "allowed" not in fw

    def test_inout_yields_ingress_and_egress(self):
        acl = _acl(direction="inout", protocol="all")
        firewalls = build_acl_firewalls(7, _node((acl,)), node_tag(7, "node.web"), _LOOKUP)
        directions = {fw["direction"] for fw in firewalls}
        assert directions == {"INGRESS", "EGRESS"}


class TestEndpointResolution:
    def test_omitted_endpoint_is_any(self):
        acl = _acl(direction="in", from_net=None)
        fw = build_acl_firewalls(7, _node((acl,)), node_tag(7, "node.web"), _LOOKUP)[0]
        assert fw["source_ranges"] == ["0.0.0.0/0"]

    def test_unresolvable_endpoint_fails_closed(self):
        acl = _acl(direction="in", from_net="net.ghost")
        node_2 = _node((acl,))
        node_tag_2 = node_tag(7, "node.web")
        with pytest.raises(RaesGceFirewallError, match="no resolvable CIDR"):
            build_acl_firewalls(7, node_2, node_tag_2, _LOOKUP)


class TestPriorityOrdering:
    def test_author_order_preserved_via_priority(self):
        acls = (
            _acl(direction="in", protocol="tcp", ports=(22,), from_net="net.dmz"),
            _acl(direction="in", action="drop", protocol="all", from_net="net.lan"),
        )
        firewalls = build_acl_firewalls(7, _node(acls), node_tag(7, "node.web"), _LOOKUP)
        assert [fw["priority"] for fw in firewalls] == [1000, 1001]


def _svc_node(services: tuple[RaesPlanServicePort, ...], *, address: str = "node.web") -> RaesPlanNode:
    return RaesPlanNode(
        address=address,
        name=address.rsplit(".", 1)[-1],
        os_family="linux",
        count=1,
        network_addresses=("net.lan",),
        services=services,
    )


_SVC_SOURCES = ("10.9.0.0/24", "10.9.1.0/24")


class TestServiceFirewalls:
    def test_no_services_yields_no_firewalls(self):
        assert (
            build_service_firewalls(7, _svc_node(()), node_tag(7, "node.web"), _SVC_SOURCES, base_priority=1001) == []
        )

    def test_tcp_service_opens_ingress_from_same_range_sources(self):
        node = _svc_node((RaesPlanServicePort(port=80, protocol="tcp", name="http"),))
        fws = build_service_firewalls(7, node, node_tag(7, "node.web"), _SVC_SOURCES, base_priority=1001)
        assert len(fws) == 1
        fw = fws[0]
        assert fw["direction"] == "INGRESS"
        assert fw["allowed"] == [{"IPProtocol": "tcp", "ports": ["80"]}]
        assert fw["target_tags"] == [node_tag(7, "node.web")]
        # sourced only from same-range CIDRs (deduped + deterministic), never 0.0.0.0/0
        assert fw["source_ranges"] == ["10.9.0.0/24", "10.9.1.0/24"]
        assert "0.0.0.0/0" not in fw["source_ranges"]
        assert fw["priority"] == 1001

    def test_udp_protocol_is_preserved(self):
        node = _svc_node((RaesPlanServicePort(port=53, protocol="udp", name="dns"),))
        fw = build_service_firewalls(7, node, node_tag(7, "node.web"), _SVC_SOURCES, base_priority=1001)[0]
        assert fw["allowed"] == [{"IPProtocol": "udp", "ports": ["53"]}]

    def test_ports_aggregated_per_protocol_sorted(self):
        node = _svc_node(
            (
                RaesPlanServicePort(port=443, protocol="tcp"),
                RaesPlanServicePort(port=80, protocol="tcp"),
            )
        )
        fws = build_service_firewalls(7, node, node_tag(7, "node.web"), _SVC_SOURCES, base_priority=1001)
        assert len(fws) == 1
        assert fws[0]["allowed"] == [{"IPProtocol": "tcp", "ports": ["80", "443"]}]

    def test_tcp_and_udp_yield_two_rules_deterministic_order(self):
        node = _svc_node(
            (
                RaesPlanServicePort(port=53, protocol="udp"),
                RaesPlanServicePort(port=80, protocol="tcp"),
            )
        )
        fws = build_service_firewalls(7, node, node_tag(7, "node.web"), _SVC_SOURCES, base_priority=1001)
        assert [fw["allowed"][0]["IPProtocol"] for fw in fws] == ["tcp", "udp"]
        assert [fw["priority"] for fw in fws] == [1001, 1002]

    def test_source_cidrs_deduped_and_sorted(self):
        node = _svc_node((RaesPlanServicePort(port=80, protocol="tcp"),))
        fw = build_service_firewalls(
            7, node, node_tag(7, "node.web"), ("10.9.1.0/24", "10.9.0.0/24", "10.9.1.0/24"), base_priority=1001
        )[0]
        assert fw["source_ranges"] == ["10.9.0.0/24", "10.9.1.0/24"]

    def test_empty_sources_fail_closed(self):
        node = _svc_node((RaesPlanServicePort(port=80, protocol="tcp"),))
        node_tag_2 = node_tag(7, "node.web")
        with pytest.raises(RaesGceFirewallError, match="source"):
            build_service_firewalls(7, node, node_tag_2, (), base_priority=1001)

    def test_priority_overflow_fails_closed(self):
        node = _svc_node((RaesPlanServicePort(port=80, protocol="tcp"),))
        node_tag_2 = node_tag(7, "node.web")
        with pytest.raises(RaesGceFirewallError, match="priorit"):
            build_service_firewalls(7, node, node_tag_2, _SVC_SOURCES, base_priority=10**9)
