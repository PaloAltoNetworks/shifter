"""Tests for the RAES-native GCE range-cell plan builder (ADR-031, ADR-032).

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

from config import (
    GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    GCE_PARTICIPANT_READINESS_CONTRACT_V1,
    GCERangeCellConfig,
    GCERangeImageProfile,
)
from gcp_range_cell_types import GceEgressPolicy
from raes_access import RealizedAccessBinding
from raes_gcp_firewall import node_tag
from raes_gcp_plan import RaesGcePlanError, build_raes_range_cell_plan
from raes_identity import RESERVED_MANAGEMENT_LOGIN
from raes_plan import RaesPlan, RaesPlanAcl, RaesPlanImage, RaesPlanNetwork, RaesPlanNode, RaesPlanServicePort


def _config(*, network_mode: str = "vpc-per-range", network_id: str = "") -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="proj-1",
        region="us-east1",
        zone="us-east1-b",
        network_mode=network_mode,
        network_id=network_id,
        portal_network_cidrs=("203.0.113.0/24",),
    )


def _network(address: str = "net.a", *, name: str = "lan", cidr: str = "10.0.0.0/24") -> RaesPlanNetwork:
    return RaesPlanNetwork(address=address, name=name, cidr=cidr)


def _node(
    address: str = "node.a",
    *,
    name: str = "victim",
    count: int = 1,
    networks: tuple[str, ...] = ("net.a",),
    os_family: str = "linux",
    acls: tuple[RaesPlanAcl, ...] = (),
    services: tuple[RaesPlanServicePort, ...] = (),
    network_selection_open: bool = False,
) -> RaesPlanNode:
    return RaesPlanNode(
        address=address,
        name=name,
        os_family=os_family,
        count=count,
        network_addresses=networks,
        network_selection_open=network_selection_open,
        image=RaesPlanImage(name="kali"),
        acls=acls,
        services=services,
    )


def _plan(nodes: tuple[RaesPlanNode, ...], networks: tuple[RaesPlanNetwork, ...]) -> RaesPlan:
    return RaesPlan(raes_version="3.5.0", nodes=nodes, networks=networks)


def _resolver(profile: GCERangeImageProfile | None = None):
    resolved = profile or GCERangeImageProfile(source_image="projects/x/global/images/kali-1")
    return lambda node: resolved


class TestNetworkMode:
    def test_vpc_per_range_manages_its_own_network(self):
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert plan["manage_network"] is True
        assert plan["network"]["name"] == "shifter-range-7"

    def test_shared_vpc_reuses_platform_network(self):
        config = _config(network_mode="shared-vpc", network_id="projects/proj-1/global/networks/shared")
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), config)
        assert plan["manage_network"] is False
        assert plan["network"]["name"] == "shared"

    def test_open_network_selection_is_materialized_by_gce_adapter(self):
        portable = _plan((_node(networks=(), network_selection_open=True),), ())

        plan = build_raes_range_cell_plan("req-1", 7, portable, _resolver(), _config())

        assert portable.networks == ()
        assert portable.nodes[0].network_addresses == ()
        assert plan["subnets"][0]["uuid"] == "backend.gce.network.default"
        assert plan["subnets"][0]["cidr"] == "172.16.0.0/28"
        assert plan["instances"][0]["subnet_name"] == "backend-default"

    def test_open_network_avoids_authored_and_portal_cidrs(self):
        config = GCERangeCellConfig(
            project_id="proj-1",
            region="us-east1",
            zone="us-east1-b",
            network_mode="vpc-per-range",
            portal_network_cidrs=("172.16.0.0/28",),
        )
        portable = _plan(
            (_node(networks=(), network_selection_open=True),),
            (_network(cidr="172.16.0.16/28"),),
        )

        plan = build_raes_range_cell_plan("req-1", 7, portable, _resolver(), config)

        assert plan["subnets"][-1]["cidr"] == "172.16.0.32/28"

    def test_shared_vpc_open_network_uses_tenant_allocation(self):
        config = _config(network_mode="shared-vpc", network_id="projects/proj-1/global/networks/shared")
        portable = _plan((_node(networks=(), network_selection_open=True),), ())

        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            portable,
            _resolver(),
            config,
            allocated_network_cidr="10.90.0.0/28",
        )

        assert plan["subnets"][0]["cidr"] == "10.90.0.0/28"

    def test_shared_vpc_open_network_requires_tenant_allocation(self):
        config = _config(network_mode="shared-vpc", network_id="projects/proj-1/global/networks/shared")
        portable = _plan((_node(networks=(), network_selection_open=True),), ())

        with pytest.raises(RaesGcePlanError, match="tenant-allocated"):
            build_raes_range_cell_plan("req-1", 7, portable, _resolver(), config)

    def test_shared_vpc_teardown_reconstructs_names_when_reservation_never_existed(self):
        config = _config(network_mode="shared-vpc", network_id="projects/proj-1/global/networks/shared")
        portable = _plan((_node(networks=(), network_selection_open=True),), ())

        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            portable,
            _resolver(),
            config,
            reconstruct_for_teardown=True,
        )

        assert plan["subnets"][0]["resource_name"] == "shifter-r-7-backend-default"
        assert plan["instances"][0]["resource_name"]


class TestSubnets:
    def test_subnet_from_authored_cidr(self):
        plan = build_raes_range_cell_plan(
            "req-1", 7, _plan((_node(),), (_network(cidr="10.9.0.0/24"),)), _resolver(), _config()
        )
        subnet = plan["subnets"][0]
        assert subnet["cidr"] == "10.9.0.0/24"
        assert subnet["name"] == "lan"
        assert subnet["uuid"] == "net.a"

    def test_network_without_cidr_fails_loud(self):
        networks = (RaesPlanNetwork(address="net.a", name="lan", cidr=None),)
        plan_2 = _plan((_node(),), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="no cidr"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_oversized_subnet_fails_closed_before_enumerating_hosts(self):
        # A universal (/0) or otherwise huge authored CIDR must be rejected before the
        # planner tries to materialize its host list (fail-closed; avoids a DoS and can
        # never be a legitimate range subnet or service source).
        plan_2 = _plan((_node(),), (_network(cidr="10.0.0.0/8"),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="larger than /16"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_ipv6_subnet_fails_loud_without_leaking_authored_cidr(self):
        # #1568: a non-IPv4 (IPv6) subnet is an unsupported capability. This pure plan
        # builder is the provisioner backstop for persisted/replayed plans -- it fails
        # loud BEFORE apply reaches any _ensure_* client mutation. The error text is
        # forwarded by raes_range_ops into failure events, so it must not echo the
        # authored network literal.
        authored_cidr = "fd00:dead:beef::/64"
        plan = _plan((_node(),), (_network(cidr=authored_cidr),))
        resolver = _resolver()
        config = _config()
        with pytest.raises(RaesGcePlanError) as excinfo:
            build_raes_range_cell_plan("req-1", 7, plan, resolver, config)
        message = str(excinfo.value)
        assert "IPv4" in message
        lowered = message.lower()
        for literal in ("fd00", "dead", "beef"):
            assert literal not in lowered


class TestInstances:
    def test_single_node_gets_first_usable_ip(self):
        plan = build_raes_range_cell_plan(
            "req-1", 7, _plan((_node(),), (_network(cidr="10.0.0.0/24"),)), _resolver(), _config()
        )
        instance = plan["instances"][0]
        # GCP reserves .0/.1/.2 (net, gw, reserved) and the top two; first usable is .3.
        assert instance["private_ip"] == "10.0.0.3"
        assert instance["role"] == "raes-node"
        assert instance["os_type"] == "linux"
        assert instance["profile"].source_image == "projects/x/global/images/kali-1"
        assert instance["attach_service_account"] is False

    def test_count_fans_out_to_distinct_instances_and_ips(self):
        node = _node(count=3)
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        instances = plan["instances"]
        assert len(instances) == 3
        assert [i["name"] for i in instances] == ["victim-0", "victim-1", "victim-2"]
        assert sorted(i["private_ip"] for i in instances) == ["10.0.0.3", "10.0.0.4", "10.0.0.5"]
        assert len({i["resource_name"] for i in instances}) == 3

    def test_windows_os_family_drives_os_type(self):
        node = _node(os_family="windows")
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        assert plan["instances"][0]["os_type"] == "windows"

    def test_too_many_instances_for_subnet_fails_loud(self):
        # /30 has zero usable guest addresses after GCP reserves both ends.
        networks = (_network(cidr="10.0.0.0/30"),)
        plan_2 = _plan((_node(),), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="usable addresses"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_preconfigured_machine_host_is_rejected_before_raes_realization(self):
        """RAES cannot publish READY without the participant image canary."""
        profile = GCERangeImageProfile(
            source_machine_image="projects/proj-1/global/machineImages/participant-v1",
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant",
            participant_username="analyst",
            participant_readiness_contract=GCE_PARTICIPANT_READINESS_CONTRACT_V1,
            participant_readiness_manifest_sha256="a" * 64,
            host_ssh_username="operator",
        )
        plan = _plan((_node(),), (_network(),))
        resolver = _resolver(profile)
        config = _config()

        with pytest.raises(RaesGcePlanError, match="participant readiness"):
            build_raes_range_cell_plan("req-1", 7, plan, resolver, config)


class TestPlacementErrors:
    def test_node_without_network_fails_loud(self):
        node = _node(networks=())
        plan_2 = _plan((node,), (_network(),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="no network"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)

    def test_explicit_empty_network_selection_is_not_defaulted(self):
        node = _node(networks=(), network_selection_open=False)
        plan_2 = _plan((node,), ())

        with pytest.raises(RaesGcePlanError, match="no network"):
            build_raes_range_cell_plan("req-1", 7, plan_2, _resolver(), _config())

    def test_node_referencing_undeclared_network_fails_loud(self):
        node = _node(networks=("net.missing",))
        plan_2 = _plan((node,), (_network(),))
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="undeclared network"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)


class TestFirewalls:
    def test_base_range_firewalls_are_present(self):
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        names = {fw["name"] for fw in plan["firewalls"]}
        # Reused neutral base plan: per-subnet ingress + egress posture.
        assert any("ingress" in name for name in names)
        assert any("egress-deny" in name for name in names)

    @pytest.mark.parametrize("allow_public_web_egress", [False, True])
    def test_resolved_image_profile_controls_public_web_egress(self, allow_public_web_egress):
        profile = GCERangeImageProfile(
            source_image="projects/x/global/images/kali-1",
            allow_public_web_egress=allow_public_web_egress,
        )
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(profile),
            _config(),
        )
        web_rules = [firewall for firewall in plan["firewalls"] if firewall["name"] == "shifter-r-7-egress-web"]
        assert bool(web_rules) is allow_public_web_egress
        if web_rules:
            assert web_rules[0]["allowed"] == [{"IPProtocol": "tcp", "ports": ["80", "443"]}]

    def test_zero_egress_overrides_a_web_permitting_profile(self):
        """A pinned `none` range opens no public-web egress lane, even if the profile would."""
        profile = GCERangeImageProfile(
            source_image="projects/x/global/images/kali-1",
            allow_public_web_egress=True,
        )
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(profile),
            _config(),
            egress_policy=GceEgressPolicy(mode="none"),
        )
        names = {fw["name"] for fw in plan["firewalls"]}
        # The default egress-deny stays; the public-web lane is suppressed.
        assert any("egress-deny" in name for name in names)
        assert "shifter-r-7-egress-web" not in names

    def test_deny_all_also_suppresses_the_web_egress_lane(self):
        """deny-all forbids general egress too; a web-permitting profile must not leak."""
        profile = GCERangeImageProfile(
            source_image="projects/x/global/images/kali-1",
            allow_public_web_egress=True,
        )
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(profile),
            _config(),
            egress_policy=GceEgressPolicy(mode="deny-all"),
        )
        names = {fw["name"] for fw in plan["firewalls"]}
        assert any("egress-deny" in name for name in names)
        assert "shifter-r-7-egress-web" not in names

    def test_authored_acls_realized_as_node_firewalls(self):
        acl = RaesPlanAcl(
            name="ssh", action="accept", direction="in", protocol="tcp", ports=(22,), from_net="net.a", to_net=None
        )
        node = _node(acls=(acl,))
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        acl_firewalls = [fw for fw in plan["firewalls"] if fw.get("target_tags") == [node_tag(7, "node.a")]]
        assert len(acl_firewalls) == 1
        assert acl_firewalls[0]["direction"] == "INGRESS"
        assert acl_firewalls[0]["allowed"] == [{"IPProtocol": "tcp", "ports": ["22"]}]

    def test_instance_carries_node_tag_for_acl_targeting(self):
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert node_tag(7, "node.a") in plan["instances"][0]["tags"]


def _service_firewalls(plan: dict, address: str) -> list[dict]:
    tag = node_tag(7, address)
    return [fw for fw in plan["firewalls"] if fw.get("target_tags") == [tag] and fw["direction"] == "INGRESS"]


class TestServiceFirewalls:
    def test_authored_service_realized_as_node_ingress_firewall(self):
        node = _node(services=(RaesPlanServicePort(port=80, protocol="tcp", name="http"),))
        plan = build_raes_range_cell_plan(
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
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert _service_firewalls(plan, "node.a") == []

    def test_service_firewall_is_count_independent(self):
        node = _node(count=3, services=(RaesPlanServicePort(port=80, protocol="tcp"),))
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
        # One shared node-tag rule regardless of instance fan-out (no per-instance dup).
        assert len(_service_firewalls(plan, "node.a")) == 1

    def test_service_reachable_from_other_same_range_network_not_another_range(self):
        networks = (
            _network("net.a", name="lan", cidr="10.9.0.0/24"),
            _network("net.b", name="dmz", cidr="10.9.1.0/24"),
        )
        node = _node("node.a", networks=("net.a",), services=(RaesPlanServicePort(port=80, protocol="tcp"),))
        peer = _node("node.b", name="peer", networks=("net.b",))
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node, peer), networks), _resolver(), _config())
        svc = _service_firewalls(plan, "node.a")[0]
        assert svc["source_ranges"] == ["10.9.0.0/24", "10.9.1.0/24"]
        assert "10.99.0.0/24" not in svc["source_ranges"]  # not another range

    def test_authored_acl_outranks_service_allow(self):
        acl = RaesPlanAcl(
            name="deny", action="drop", direction="in", protocol="tcp", ports=(80,), from_net="net.a", to_net=None
        )
        node = _node(acls=(acl,), services=(RaesPlanServicePort(port=80, protocol="tcp"),))
        plan = build_raes_range_cell_plan("req-1", 7, _plan((node,), (_network(),)), _resolver(), _config())
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
        node = _node(services=(RaesPlanServicePort(port=80, protocol="tcp"),))
        networks = (_network(cidr="203.0.113.0/24"),)
        plan_2 = _plan((node,), networks)
        resolver_2 = _resolver()
        config_2 = _config()
        with pytest.raises(RaesGcePlanError, match="portal"):
            build_raes_range_cell_plan("req-1", 7, plan_2, resolver_2, config_2)


class TestParticipantAccess:
    """Joined interactive access lands on the right instance (#1710)."""

    @staticmethod
    def _binding(target="node.a", channel="ssh", username="analyst"):
        return RealizedAccessBinding(
            target_address=target,
            channel=channel,
            account_address=f"acct.{username}",
            username=username,
            auth_method="key" if channel == "ssh" else "password",
        )

    def test_no_bindings_leaves_every_instance_without_access(self):
        plan = build_raes_range_cell_plan("req-1", 7, _plan((_node(),), (_network(),)), _resolver(), _config())
        assert plan["instances"][0]["participant_access_channels"] == []
        assert plan["instances"][0]["participant_access_usernames"] == {}

    def test_channels_and_usernames_land_on_the_declared_instance(self):
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(),
            _config(),
            access_bindings=(self._binding(),),
        )
        instance = plan["instances"][0]
        assert instance["participant_access_channels"] == ["ssh"]
        assert instance["participant_access_usernames"] == {"ssh": "analyst"}

    def test_per_channel_usernames_are_kept_distinct(self):
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(os_family="windows"),), (_network(),)),
            _resolver(),
            _config(),
            access_bindings=(
                self._binding(channel="ssh", username="sshuser"),
                self._binding(channel="rdp", username="rdpuser"),
            ),
        )
        instance = plan["instances"][0]
        assert sorted(instance["participant_access_channels"]) == ["rdp", "ssh"]
        assert instance["participant_access_usernames"] == {"ssh": "sshuser", "rdp": "rdpuser"}

    def test_a_binding_never_cross_wires_to_another_node(self):
        """Grouping is by target address: an undeclared node stays access-free."""
        nodes = (_node(address="node.a", name="web"), _node(address="node.b", name="db"))
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan(nodes, (_network(),)),
            _resolver(),
            _config(),
            access_bindings=(self._binding(target="node.a"),),
        )
        by_uuid = {instance["uuid"]: instance for instance in plan["instances"]}
        assert by_uuid["node.a#0"]["participant_access_channels"] == ["ssh"]
        assert by_uuid["node.b#0"]["participant_access_channels"] == []
        assert by_uuid["node.b#0"]["participant_access_usernames"] == {}

    def test_the_management_login_is_not_the_participant_login(self):
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(),
            _config(),
            access_bindings=(self._binding(),),
        )
        instance = plan["instances"][0]
        assert instance["ssh_username"] == RESERVED_MANAGEMENT_LOGIN
        assert instance["participant_access_usernames"]["ssh"] != RESERVED_MANAGEMENT_LOGIN


class TestRangeOwnedNat:
    """A non-`none` range owns a Cloud Router+NAT; a `none` range has none (PLAT-238)."""

    def test_status_quo_range_gets_a_router_nat_scoped_to_its_subnets(self):
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(),
            _config(),
            egress_policy=GceEgressPolicy(mode="status-quo"),
        )
        router_nat = plan.get("router_nat")
        assert router_nat is not None
        assert router_nat["router_name"] == "shifter-r-7-nat-router"
        expected = [subnet["self_link"] for subnet in plan["subnets"]]
        assert router_nat["subnetwork_self_links"] == expected
        assert expected  # the range has at least one subnet to NAT

    def test_none_range_has_no_router_nat(self):
        plan = build_raes_range_cell_plan(
            "req-1",
            7,
            _plan((_node(),), (_network(),)),
            _resolver(),
            _config(),
            egress_policy=GceEgressPolicy(mode="none"),
        )
        assert "router_nat" not in plan
