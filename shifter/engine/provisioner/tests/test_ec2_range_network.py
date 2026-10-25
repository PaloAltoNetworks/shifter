"""EC2 allocation realizes open intent without broadening reachability."""

from dataclasses import replace
from uuid import UUID

import pytest

from ec2_range_network import Ec2NetworkConfig, Ec2NetworkError, plan_ec2_network
from raes_ec2_image import VerifiedEc2Image
from raes_plan import RaesPlan, RaesPlanAcl, RaesPlanNetwork, RaesPlanNode


def config():
    return Ec2NetworkConfig(
        environment="test",
        region="us-east-2",
        zone="us-east-2a",
        vpc_id="vpc-" + "0" * 17,
        vpc_cidr="10.50.0.0/16",
        base_route_table_id="rtb-00000000000000000",
        management_cidrs=("10.42.0.0/24",),
        access_cidrs=("10.42.1.0/24",),
        broker_cidrs=("10.42.2.10/32",),
    )


def topology():
    return RaesPlan(
        raes_version="3.5.0",
        networks=(RaesPlanNetwork(address="net.lan", name="lan"),),
        nodes=(
            RaesPlanNode(address="node.host", name="host", os_family="linux", count=1, network_addresses=("net.lan",)),
        ),
    )


def image():
    return VerifiedEc2Image(
        "ami-00000000000000000", "m7i.large", "/dev/sda1", "snap-00000000000000000", 30, "gp3", "x86_64", 2222
    )


def build(raes=None, cfg=None, **kwargs):
    from ec2_range_cleanup import Ec2CleanupScope

    cfg = cfg or config()
    return plan_ec2_network(
        raes or topology(),
        config=cfg,
        scope=Ec2CleanupScope(cfg.environment, cfg.region, cfg.vpc_id, UUID(int=1), UUID(int=2), 7),
        allocated_cidrs=kwargs.get("allocated", {"net.lan": "10.50.1.0/28"}),
        images={"node.host": image()},
        participant_channels=kwargs.get("channels", {"node.host": ("ssh",)}),
        egress_mode=kwargs.get("mode", "deny-all"),
    )


def test_duplicate_participant_channels_collapse_to_one_grant():
    # Two participants sharing the ssh channel both yield tcp/22 from the access CIDRs;
    # AWS rejects a permission appearing twice in one authorize call, so the plan must
    # collapse the exact duplicate to a single grant.
    group = build(channels={"node.host": ("ssh", "ssh")}).groups[0]
    ssh_rules = [rule for rule in group.ingress if rule["IpProtocol"] == "tcp" and rule.get("FromPort") == 22]
    assert len(ssh_rules) == 1
    assert all(group.ingress.count(rule) == 1 for rule in group.ingress)


def test_plan_uses_reserved_subnet_without_rewriting_authored_topology():
    source = topology()
    planned = build(source)
    assert source.networks[0].cidr is None
    assert planned.guests[0].private_ip == "10.50.1.4"
    assert planned.subnets[0].cidr == "10.50.1.0/28"
    group = planned.groups[0]
    assert any(
        rule["FromPort"] == 2222 and rule["IpRanges"] == [{"CidrIp": "10.42.0.0/24"}]
        for rule in group.ingress
        if rule["IpProtocol"] == "tcp"
    )
    assert any(
        rule["FromPort"] == 22 and rule["IpRanges"] == [{"CidrIp": "10.42.1.0/24"}]
        for rule in group.ingress
        if rule["IpProtocol"] == "tcp"
    )
    assert {item["CidrIp"] for rule in group.egress for item in rule.get("IpRanges", [])} == {
        "10.50.1.0/28",
        "10.42.2.10/32",
    }
    assert "0.0.0.0/0" not in str(group)


@pytest.mark.parametrize("cidr", ["10.50.1.1/28", "10.51.1.0/28", "10.50.1.0/30", "0.0.0.0/0"])
def test_invalid_allocator_result_fails_before_provider_mutation(cidr):
    with pytest.raises(Ec2NetworkError):
        build(allocated={"net.lan": cidr})


def test_explicit_network_cidr_cannot_be_silently_replaced():
    plan = topology()
    plan = replace(plan, networks=(replace(plan.networks[0], cidr="10.50.2.0/28"),))
    with pytest.raises(Ec2NetworkError):
        build(plan)


def test_security_groups_do_not_claim_to_implement_ordered_deny_acls():
    plan = topology()
    acl = RaesPlanAcl(name="deny", action="drop", direction="in", protocol="all", ports=())
    plan = replace(plan, nodes=(replace(plan.nodes[0], acls=(acl,)),))
    with pytest.raises(Ec2NetworkError, match="ACL"):
        build(plan)


def test_none_posture_refuses_broker_exception():
    with pytest.raises(Ec2NetworkError):
        build(mode="none")


def test_guest_cannot_share_a_subnet_with_management_or_broker():
    with pytest.raises(Ec2NetworkError):
        build(cfg=replace(config(), management_cidrs=("10.50.1.0/28",)))
