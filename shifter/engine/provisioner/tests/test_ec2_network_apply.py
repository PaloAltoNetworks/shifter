"""Owned network convergence removes EC2 defaults and refuses public route fallback."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from ec2_network_apply import ensure_ec2_network, peer_routes
from ec2_range_network import Ec2NetworkError
from tests.test_ec2_range_network import build


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record (never perform) the eventual-consistency readback waits."""
    calls = []
    monkeypatch.setattr("ec2_network_apply.time.sleep", calls.append)
    return calls


def api_for(plan):
    ec2 = Mock()
    cfg = plan.config
    ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": cfg.vpc_id, "CidrBlock": cfg.vpc_cidr, "State": "available"}]}
    ec2.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "RouteTableId": cfg.base_route_table_id,
                "VpcId": cfg.vpc_id,
                "Routes": [
                    {
                        "DestinationCidrBlock": "10.42.0.0/16",
                        "VpcPeeringConnectionId": "pcx-00000000000000000",
                        "State": "active",
                    }
                ],
            }
        ]
    }
    subnets, groups, tables = [], [], []
    ec2.describe_subnets.side_effect = lambda **kw: {"Subnets": deepcopy(subnets)}
    ec2.describe_security_groups.side_effect = lambda **kw: {"SecurityGroups": deepcopy(groups)}

    def subnet(**kw):
        row = {
            "SubnetId": "subnet-" + "0" * 17,
            "VpcId": kw["VpcId"],
            "CidrBlock": kw["CidrBlock"],
            "AvailabilityZone": kw["AvailabilityZone"],
            "MapPublicIpOnLaunch": False,
            "Tags": kw["TagSpecifications"][0]["Tags"],
        }
        subnets.append(row)
        return {"Subnet": deepcopy(row)}

    ec2.create_subnet.side_effect = subnet

    def group(**kw):
        groups.append(
            {
                "GroupId": "sg-00000000000000000",
                "GroupName": kw["GroupName"],
                "VpcId": kw["VpcId"],
                "Tags": kw["TagSpecifications"][0]["Tags"],
                "IpPermissions": [],
                "IpPermissionsEgress": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            }
        )
        return {"GroupId": groups[-1]["GroupId"]}

    ec2.create_security_group.side_effect = group
    for direction, key in (("ingress", "IpPermissions"), ("egress", "IpPermissionsEgress")):
        getattr(ec2, "revoke_security_group_" + direction).side_effect = lambda key=key, **kw: groups[0].update(
            {key: []}
        )
        getattr(ec2, "authorize_security_group_" + direction).side_effect = lambda key=key, **kw: groups[0].update(
            {key: deepcopy(kw["IpPermissions"])}
        )

    def table(**kw):
        row = {
            "RouteTableId": "rtb-11111111111111111",
            "VpcId": cfg.vpc_id,
            "Tags": kw["TagSpecifications"][0]["Tags"],
            "Routes": [{"DestinationCidrBlock": cfg.vpc_cidr, "GatewayId": "local", "State": "active"}],
            "Associations": [],
        }
        tables.append(row)
        return {"RouteTable": deepcopy(row)}

    ec2.create_route_table.side_effect = table
    base = ec2.describe_route_tables.return_value

    def describe_tables(**kw):
        if kw.get("RouteTableIds") == [cfg.base_route_table_id]:
            return deepcopy(base)
        associations = [row for row in kw.get("Filters", []) if row["Name"] == "association.subnet-id"]
        if associations:
            return {
                "RouteTables": deepcopy(
                    [
                        table
                        for table in tables
                        if any(row["SubnetId"] in associations[0]["Values"] for row in table["Associations"])
                    ]
                )
            }
        return {"RouteTables": deepcopy(tables)}

    ec2.describe_route_tables.side_effect = describe_tables

    def route(**kw):
        tables[0]["Routes"].append(
            {key: value for key, value in kw.items() if key != "RouteTableId"} | {"State": "active"}
        )
        return {"Return": True}

    ec2.create_route.side_effect = route

    def associate(**kw):
        tables[0]["Associations"].append(
            {
                "SubnetId": kw["SubnetId"],
                "RouteTableAssociationId": "rtbassoc-example",
                "Main": False,
                "AssociationState": {"State": "associated"},
            }
        )
        return {"AssociationId": "rtbassoc-example"}

    ec2.associate_route_table.side_effect = associate
    return ec2, subnets, groups, tables


def test_reconciles_private_subnet_and_narrow_rules_without_inheriting_default_egress():
    plan = build()
    ec2, subnets, groups, tables = api_for(plan)
    result = ensure_ec2_network(plan, ec2)
    assert result.subnets["net.lan"] == subnets[0]["SubnetId"]
    assert result.groups["node.host"] == groups[0]["GroupId"]
    assert "0.0.0.0/0" not in str(groups[0]["IpPermissionsEgress"])
    assert all(route["DestinationCidrBlock"] != "0.0.0.0/0" for route in tables[0]["Routes"])
    before = (ec2.create_subnet.call_count, ec2.create_security_group.call_count, ec2.create_route_table.call_count)
    assert ensure_ec2_network(plan, ec2) == result
    assert before == (
        ec2.create_subnet.call_count,
        ec2.create_security_group.call_count,
        ec2.create_route_table.call_count,
    )


def test_owned_lookups_never_bound_describe_with_max_results():
    # MaxResults makes EC2 emit NextToken from its account-wide scan, which the owned
    # lookups read as an incomplete result and reject -- spuriously failing provisioning
    # once the account holds more resources of a type than the page (#1826). The filtered
    # describes must omit MaxResults so a genuine NextToken means a truly oversized result.
    plan = build()
    ec2, _subnets, _groups, _tables = api_for(plan)
    ensure_ec2_network(plan, ec2)
    for describe in (ec2.describe_subnets, ec2.describe_security_groups, ec2.describe_route_tables):
        assert describe.call_count
        assert all("MaxResults" not in call.kwargs for call in describe.call_args_list)


def test_peer_routes_never_fall_back_to_a_default_nat_or_gateway():
    plan = build()
    ec2, *_ = api_for(plan)
    ec2.describe_route_tables.side_effect = None
    ec2.describe_route_tables.return_value["RouteTables"][0]["Routes"] = [
        {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-example", "State": "active"}
    ]
    with pytest.raises(Ec2NetworkError):
        peer_routes(plan.config, ec2)
    ec2.create_subnet.assert_not_called()


def test_existing_foreign_subnet_blocks_network_creation(sleeps):
    plan = build()
    ec2, subnets, *_ = api_for(plan)
    subnets.append({"SubnetId": "subnet-" + "f" * 17, "Tags": []})
    with pytest.raises(Ec2NetworkError):
        ensure_ec2_network(plan, ec2)
    ec2.create_security_group.assert_not_called()
    # Ownership conflicts are never mistaken for read-after-write lag.
    assert sleeps == []


@pytest.mark.parametrize("lost_operation", ["create_route", "associate_route_table"])
def test_network_is_not_ready_until_routes_and_associations_are_observable(lost_operation, sleeps):
    plan = build()
    ec2, *_ = api_for(plan)
    getattr(ec2, lost_operation).side_effect = None
    with pytest.raises(Ec2NetworkError, match="readback"):
        ensure_ec2_network(plan, ec2)
    ec2.create_security_group.assert_not_called()
    # Retried across the bounded consistency window, then failed closed.
    assert len(sleeps) == 7
    assert sum(sleeps) <= 12


def test_created_resources_converge_through_eventually_consistent_readback(sleeps):
    # EC2 is eventually consistent: a describe right after a create can omit the new
    # resource. Convergence must re-read it, never re-create it.
    plan = build()
    ec2, subnets, groups, _tables = api_for(plan)
    invisible_once = set()

    def lag_after(create_name, describe_name, empty_key):
        create, describe = getattr(ec2, create_name).side_effect, getattr(ec2, describe_name).side_effect

        def created(**kw):
            invisible_once.add(describe_name)
            return create(**kw)

        def described(**kw):
            if describe_name in invisible_once:
                invisible_once.discard(describe_name)
                return {empty_key: []}
            return describe(**kw)

        getattr(ec2, create_name).side_effect = created
        getattr(ec2, describe_name).side_effect = described

    lag_after("create_subnet", "describe_subnets", "Subnets")
    lag_after("create_security_group", "describe_security_groups", "SecurityGroups")
    lag_after("create_route_table", "describe_route_tables", "RouteTables")

    result = ensure_ec2_network(plan, ec2)

    assert result.subnets["net.lan"] == subnets[0]["SubnetId"]
    assert result.groups["node.host"] == groups[0]["GroupId"]
    assert ec2.create_subnet.call_count == ec2.create_security_group.call_count == 1
    assert ec2.create_route_table.call_count == 1
    assert ec2.authorize_security_group_ingress.call_count == 1
    assert sleeps == [0.5, 0.5, 0.5]


def test_stale_rule_readback_is_reread_without_reapplying_grants(sleeps):
    plan = build()
    ec2, *_ = api_for(plan)
    real = ec2.describe_security_groups.side_effect
    stale = {"remaining": 1}

    def describe(**kw):
        response = real(**kw)
        if kw.get("GroupIds") and stale["remaining"]:
            stale["remaining"] -= 1
            response["SecurityGroups"][0]["IpPermissions"] = []
        return response

    ec2.describe_security_groups.side_effect = describe
    ensure_ec2_network(plan, ec2)
    assert stale["remaining"] == 0
    assert ec2.authorize_security_group_ingress.call_count == 1
    assert sleeps == [0.5]


def test_subnet_with_foreign_explicit_route_table_is_not_reassociated():
    plan = build()
    ec2, *_ = api_for(plan)
    original = ec2.describe_route_tables.side_effect

    def describe(**kw):
        if any(row["Name"] == "association.subnet-id" for row in kw.get("Filters", [])):
            return {"RouteTables": [{"RouteTableId": "rtb-22222222222222222", "Tags": []}]}
        return original(**kw)

    ec2.describe_route_tables.side_effect = describe
    with pytest.raises(Ec2NetworkError, match="another route table"):
        ensure_ec2_network(plan, ec2)
    ec2.associate_route_table.assert_not_called()
