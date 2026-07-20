"""Tests for the ACES-native GCE range-cell plan builder (ADR-031, ADR-032).

Exercises the topology -> RangeCellPlan mapping: network mode (vpc-per-range vs
shared-vpc), authored CIDRs -> subnets, nodes -> instances (count fan-out,
deterministic IP assignment skipping GCP-reserved addresses, registry-resolved
image profile, neutral labels only), and fail-loud placement errors. The image
resolver is injected (pure), so no registry/DB is touched.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_gcp_firewall import node_tag
from aces_gcp_plan import AcesGcePlanError, build_aces_range_cell_plan
from aces_plan import AcesPlan, AcesPlanAcl, AcesPlanImage, AcesPlanNetwork, AcesPlanNode, AcesPlanServicePort
from config import GCERangeCellConfig, GCERangeImageProfile


def _config(*, network_mode: str = "vpc-per-range", network_id: str = "") -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="proj-1",
        region="us-east1",
        zone="us-east1-b",
        network_mode=network_mode,
        network_id=network_id,
        portal_network_cidrs=("203.0.113.0/24",),
    )


def _network(address: str = "net.a", *, name: str = "lan", cidr: str = "10.0.0.0/24") -> AcesPlanNetwork:
    return AcesPlanNetwork(address=address, name=name, cidr=cidr)


def _node(
    address: str = "node.a",
    *,
    name: str = "victim",
    count: int = 1,
    networks: tuple[str, ...] = ("net.a",),
    os_family: str = "linux",
    acls: tuple[AcesPlanAcl, ...] = (),
    services: tuple[AcesPlanServicePort, ...] = (),
) -> AcesPlanNode:
    return AcesPlanNode(
        address=address,
        name=name,
        os_family=os_family,
        count=count,
        network_addresses=networks,
        image=AcesPlanImage(name="kali"),
        acls=acls,
        services=services,
    )


def _plan(nodes: tuple[AcesPlanNode, ...], networks: tuple[AcesPlanNetwork, ...]) -> AcesPlan:
    return AcesPlan(aces_sdl_version="0.19.1", nodes=nodes, networks=networks)


def _resolver(profile: GCERangeImageProfile | None = None):
    resolved = profile or GCERangeImageProfile(source_image="projects/x/global/images/kali-1")
    return lambda node: resolved


class TestNetworkMode:
    def test_vpc_per_range_manages_its_own_network(self):
        plan = build_aces_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert plan["manage_network"] is True
        assert plan["network"]["name"] == "shifter-range-7"

    def test_shared_vpc_reuses_platform_network(self):
        config = _config(network_mode="shared-vpc", network_id="projects/proj-1/global/networks/shared")
        plan = build_aces_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), config)
        assert plan["manage_network"] is False
        assert plan["network"]["name"] == "shared"


class TestSubnets:
    def test_subnet_from_authored_cidr(self):
        plan = build_aces_range_cell_plan(
            "req-1", 7, _plan((_node(),), (_network(cidr="10.9.0.0/24"),)), _resolver(), _config()
        )
        subnet = plan["subnets"][0]
        assert subnet["cidr"] == "10.9.0.0/24"
        assert subnet["name"] == "lan"
        assert subnet["uuid"] == "net.a"

    def test_network_without_cidr_fails_loud(self):
        networks = (AcesPlanNetwork(address="net.a", name="lan", cidr=None),)
        plan_2 = _plan((_node(),), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="no cidr"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_oversized_subnet_fails_closed_before_enumerating_hosts(self):
        # A universal (/0) or otherwise huge authored CIDR must be rejected before the
        # planner tries to materialize its host list (fail-closed; avoids a DoS and can
        # never be a legitimate range subnet or service source).
        plan_2 = _plan((_node(),), (_network(cidr="10.0.0.0/8"),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="larger than /16"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_ipv6_subnet_fails_loud_without_leaking_authored_cidr(self):
        # #1568: a non-IPv4 (IPv6) subnet is an unsupported capability. This pure plan
        # builder is the provisioner backstop for persisted/replayed plans -- it fails
        # loud BEFORE apply reaches any _ensure_* client mutation. The error text is
        # forwarded by aces_range_ops into failure events, so it must not echo the
        # authored network literal.
        authored_cidr = "fd00:dead:beef::/64"
        plan = _plan((_node(),), (_network(cidr=authored_cidr),))
        resolver = _resolver()
        config = _config()
        with pytest.raises(AcesGcePlanError) as excinfo:
            build_aces_range_cell_plan("req-1", 7, plan, resolver, config)
        message = str(excinfo.value)
        assert "IPv4" in message
        lowered = message.lower()
        for literal in ("fd00", "dead", "beef"):
            assert literal not in lowered


class TestInstances:
    def test_single_node_gets_first_usable_ip(self):
        plan = build_aces_range_cell_plan(
            "req-1", 7, _plan((_node(),), (_network(cidr="10.0.0.0/24"),)), _resolver(), _config()
        )
        instance = plan["instances"][0]
        # GCP reserves .0/.1/.2 (net, gw, reserved) and the top two; first usable is .3.
        assert instance["private_ip"] == "10.0.0.3"
        assert instance["role"] == "aces-node"
        assert instance["os_type"] == "linux"
        assert instance["profile"].source_image == "projects/x/global/images/kali-1"
        assert instance["attach_service_account"] is False

    def test_count_fans_out_to_distinct_instances_and_ips(self):
        node = _node(count=3)
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        instances = plan["instances"]
        assert len(instances) == 3
        assert [i["name"] for i in instances] == ["victim-0", "victim-1", "victim-2"]
        assert sorted(i["private_ip"] for i in instances) == ["10.0.0.3", "10.0.0.4", "10.0.0.5"]
        assert len({i["resource_name"] for i in instances}) == 3

    def test_windows_os_family_drives_os_type(self):
        node = _node(os_family="windows")
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        assert plan["instances"][0]["os_type"] == "windows"

    def test_too_many_instances_for_subnet_fails_loud(self):
        # /30 has zero usable guest addresses after GCP reserves both ends.
        networks = (_network(cidr="10.0.0.0/30"),)
        plan_2 = _plan((_node(),), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="usable addresses"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)


class TestPlacementErrors:
    def test_node_without_network_fails_loud(self):
        node = _node(networks=())
        plan_2 = _plan((node,), (_network(),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="no network"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_node_referencing_undeclared_network_fails_loud(self):
        node = _node(networks=("net.missing",))
        plan_2 = _plan((node,), (_network(),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="undeclared network"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)


class TestFirewalls:
    def test_base_range_firewalls_are_present(self):
        plan = build_aces_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        names = {fw["name"] for fw in plan["firewalls"]}
        # Reused neutral base plan: per-subnet ingress + egress posture.
        assert any("ingress" in name for name in names)
        assert any("egress-deny" in name for name in names)

    def test_authored_acls_realized_as_node_firewalls(self):
        acl = AcesPlanAcl(
            name="ssh", action="accept", direction="in", protocol="tcp", ports=(22,), from_net="net.a", to_net=None
        )
        node = _node(acls=(acl,))
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        acl_firewalls = [fw for fw in plan["firewalls"] if fw.get("target_tags") == [node_tag(7, "node.a")]]
        assert len(acl_firewalls) == 1
        assert acl_firewalls[0]["direction"] == "INGRESS"
        assert acl_firewalls[0]["allowed"] == [{"IPProtocol": "tcp", "ports": ["22"]}]

    def test_instance_carries_node_tag_for_acl_targeting(self):
        plan = build_aces_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert node_tag(7, "node.a") in plan["instances"][0]["tags"]


def _service_firewalls(plan: dict, address: str) -> list[dict]:
    tag = node_tag(7, address)
    return [fw for fw in plan["firewalls"] if fw.get("target_tags") == [tag] and fw["direction"] == "INGRESS"]


class TestServiceFirewalls:
    def test_authored_service_realized_as_node_ingress_firewall(self):
        node = _node(services=(AcesPlanServicePort(port=80, protocol="tcp", name="http"),))
        plan = build_aces_range_cell_plan(
            "req-1", 7, _plan((node,), (_network(cidr="10.9.0.0/24"),)), _resolver(), _config()
        )
        svc = _service_firewalls(plan, "node.a")
        assert len(svc) == 1
        assert svc[0]["allowed"] == [{"IPProtocol": "tcp", "ports": ["80"]}]
        assert svc[0]["source_ranges"] == ["10.9.0.0/24"]
        assert "0.0.0.0/0" not in svc[0]["source_ranges"]
        # never sourced from the portal/management CIDR
        assert "203.0.113.0/24" not in svc[0]["source_ranges"]

    def test_no_service_plan_has_no_node_ingress_firewall(self):
        plan = build_aces_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert _service_firewalls(plan, "node.a") == []

    def test_service_firewall_is_count_independent(self):
        node = _node(count=3, services=(AcesPlanServicePort(port=80, protocol="tcp"),))
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        # One shared node-tag rule regardless of instance fan-out (no per-instance dup).
        assert len(_service_firewalls(plan, "node.a")) == 1

    def test_service_reachable_from_other_same_range_network_not_another_range(self):
        networks = (
            _network("net.a", name="lan", cidr="10.9.0.0/24"),
            _network("net.b", name="dmz", cidr="10.9.1.0/24"),
        )
        node = _node("node.a", networks=("net.a",), services=(AcesPlanServicePort(port=80, protocol="tcp"),))
        peer = _node("node.b", name="peer", networks=("net.b",))
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node, peer), networks), _resolver(), _config())
        svc = _service_firewalls(plan, "node.a")[0]
        assert svc["source_ranges"] == ["10.9.0.0/24", "10.9.1.0/24"]
        assert "10.99.0.0/24" not in svc["source_ranges"]  # not another range

    def test_authored_acl_outranks_service_allow(self):
        acl = AcesPlanAcl(
            name="deny", action="drop", direction="in", protocol="tcp", ports=(80,), from_net="net.a", to_net=None
        )
        node = _node(acls=(acl,), services=(AcesPlanServicePort(port=80, protocol="tcp"),))
        plan = build_aces_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        tag = node_tag(7, "node.a")
        acl_prio = next(fw["priority"] for fw in plan["firewalls"] if fw.get("target_tags") == [tag] and "denied" in fw)
        svc_prio = next(
            fw["priority"] for fw in plan["firewalls"] if fw.get("target_tags") == [tag] and "allowed" in fw
        )
        # lower number wins in GCP: the authored ACL deny must outrank the service allow.
        assert acl_prio < svc_prio

    def test_service_source_overlapping_portal_fails_closed(self):
        # portal_network_cidrs defaults to 203.0.113.0/24; a range network overlapping it
        # must not widen a service allow onto the management/portal source range.
        node = _node(services=(AcesPlanServicePort(port=80, protocol="tcp"),))
        networks = (_network(cidr="203.0.113.0/24"),)
        plan_2 = _plan((node,), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(AcesGcePlanError, match="portal"):
            build_aces_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)
