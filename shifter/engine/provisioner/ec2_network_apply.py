"""Converge range-owned EC2 subnets, groups and private-only route tables."""

from __future__ import annotations

import ipaddress
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from ec2_range_network import Ec2GroupIntent, Ec2NetworkConfig, Ec2NetworkError, Ec2NetworkPlan, Ec2SubnetIntent

# The EC2 API is eventually consistent: a describe issued right after a create or a
# rule/route/association change can omit the new resource or show the prior state.
# Readbacks of just-converged state are retried within this bounded window (~11.5s)
# before the observation is treated as real.
_OBSERVE_ATTEMPTS = 8
_OBSERVE_INITIAL_DELAY_SECONDS = 0.5
_OBSERVE_MAX_DELAY_SECONDS = 2.0


class Ec2NetworkNotObservable(Ec2NetworkError):
    """Converged state is not (yet) visible in an EC2 readback."""


def _eventually[T](observe: Callable[[], T]) -> T:
    """Re-run a read-only observation across EC2's read-after-write window.

    Only :class:`Ec2NetworkNotObservable` is retried. Ownership, placement and
    admission failures raise immediately, and a state still unobservable after the
    window propagates. ``observe`` must never mutate.
    """
    delay = _OBSERVE_INITIAL_DELAY_SECONDS
    for _ in range(_OBSERVE_ATTEMPTS - 1):
        try:
            return observe()
        except Ec2NetworkNotObservable:
            time.sleep(delay)
            delay = min(delay * 2, _OBSERVE_MAX_DELAY_SECONDS)
    return observe()


def _created_rows(response: dict[str, Any], key: str, message: str) -> list[dict[str, Any]]:
    """Return a just-created resource's lookup, signalling when it is not yet visible."""
    rows = _rows(response, key)
    if not rows:
        raise Ec2NetworkNotObservable(message)
    return rows


@dataclass(frozen=True)
class Ec2NetworkResources:
    """Provider identities of the realized range-owned network resources."""

    subnets: dict[str, str]
    groups: dict[str, str]
    route_table_id: str


def _rows(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Require a complete lookup with at most one ownership candidate.

    Callers must not pass ``MaxResults``: EC2 derives ``NextToken`` from its
    account-wide resource scan, not the caller's filters, so a bounded page emits a
    continuation token (read here as an incomplete lookup) whenever the account holds
    more resources of that type than the page, even when the filters match one or none.
    Omitting ``MaxResults`` lets the server-side filters return the few owned matches in
    a single default page; a genuine ``NextToken`` then means a truly oversized result.
    """
    if response.get("NextToken"):
        raise Ec2NetworkError("EC2 owned-resource lookup exceeded its bound")
    values = response.get(key, [])
    if not isinstance(values, list) or len(values) > 1:
        raise Ec2NetworkError("EC2 owned-resource lookup is ambiguous")
    return values


def _owned(row: dict[str, Any], plan: Ec2NetworkPlan, subject: str) -> None:
    """Verify all ownership tags against the intended range generation."""
    tags = {item["Key"]: item["Value"] for item in row.get("Tags", [])}
    if any(tags.get(item["Key"]) != item["Value"] for item in plan.tags(subject)):
        raise Ec2NetworkError("EC2 network resource belongs to another range or generation")


def peer_routes(config: Ec2NetworkConfig, ec2: BaseClient) -> dict[str, str]:
    """Select only active peering routes for exact private platform destinations."""
    rows = _rows(ec2.describe_route_tables(RouteTableIds=[config.base_route_table_id]), "RouteTables")
    if not rows or rows[0].get("VpcId") != config.vpc_id:
        raise Ec2NetworkError("EC2 base routing belongs to a different network")
    destinations = {*config.management_cidrs, *config.access_cidrs, *config.broker_cidrs}
    result = {}
    for destination in sorted(destinations):
        result[destination] = _peer_for_destination(rows[0].get("Routes", []), destination)
    return result


def _peer_for_destination(routes: list[dict[str, Any]], destination: str) -> str:
    """Choose the unique most-specific active private peer for one destination."""
    target = ipaddress.IPv4Network(destination)
    candidates = []
    for route in routes:
        prefix = route.get("DestinationCidrBlock")
        if not prefix or route.get("State") != "active" or not route.get("VpcPeeringConnectionId"):
            continue
        network = ipaddress.IPv4Network(prefix)
        if network.prefixlen and target.subnet_of(network):
            candidates.append((network.prefixlen, route["VpcPeeringConnectionId"]))
    if not candidates:
        raise Ec2NetworkError("EC2 platform destination has no active private peering route")
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise Ec2NetworkError("EC2 platform destination has ambiguous routing")
    return candidates[0][1]


def _subnet(plan: Ec2NetworkPlan, wanted: Ec2SubnetIntent, ec2: BaseClient) -> str:
    """Converge one reserved subnet without adopting foreign or exposed resources."""
    filters = [{"Name": "vpc-id", "Values": [plan.config.vpc_id]}, {"Name": "cidr-block", "Values": [wanted.cidr]}]
    rows = _rows(ec2.describe_subnets(Filters=filters), "Subnets")
    if not rows:
        try:
            ec2.create_subnet(
                VpcId=plan.config.vpc_id,
                CidrBlock=wanted.cidr,
                AvailabilityZone=plan.config.zone,
                TagSpecifications=[{"ResourceType": "subnet", "Tags": plan.tags(wanted.address)}],
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvalidSubnet.Conflict":
                raise
        rows = _eventually(
            lambda: _created_rows(
                ec2.describe_subnets(Filters=filters), "Subnets", "EC2 subnet creation is not yet observable"
            )
        )
    row = rows[0]
    _owned(row, plan, wanted.address)
    _verify_subnet(plan, wanted, row)
    return row["SubnetId"]


def _verify_subnet(plan: Ec2NetworkPlan, wanted: Ec2SubnetIntent, row: dict[str, Any]) -> None:
    """Require exact subnet placement and disabled public or IPv6 addressing."""
    if (
        row.get("VpcId") != plan.config.vpc_id
        or row.get("CidrBlock") != wanted.cidr
        or row.get("AvailabilityZone") != plan.config.zone
        or row.get("MapPublicIpOnLaunch") is not False
        or row.get("AssignIpv6AddressOnCreation")
        or row.get("Ipv6CidrBlockAssociationSet")
    ):
        raise Ec2NetworkError("EC2 subnet placement or address exposure differs from intent")


def _permissions(values: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> frozenset[str]:
    """Compare semantic grants across AWS's protocol/port aggregation."""
    normalized = []
    for rule in values:
        if rule.get("UserIdGroupPairs") or rule.get("PrefixListIds"):
            raise Ec2NetworkError("EC2 guest security group has an unmodelled source identity")
        protocol = rule["IpProtocol"]
        ports = [] if protocol == "-1" else [rule.get("FromPort"), rule.get("ToPort")]
        for key, address_key in (("IpRanges", "CidrIp"), ("Ipv6Ranges", "CidrIpv6")):
            for network in rule.get(key, []):
                normalized.append(json.dumps([protocol, ports, key, network[address_key]]))
    return frozenset(normalized)


def _rules(ec2: BaseClient, group: dict[str, Any], direction: str, wanted: tuple[dict[str, Any], ...]) -> None:
    """Replace security group grants with the exact intended rules."""
    key = "IpPermissions" if direction == "ingress" else "IpPermissionsEgress"
    current = group.get(key, [])
    if _permissions(current) == _permissions(wanted):
        return
    if current:
        getattr(ec2, "revoke_security_group_" + direction)(GroupId=group["GroupId"], IpPermissions=current)
    if wanted:
        getattr(ec2, "authorize_security_group_" + direction)(GroupId=group["GroupId"], IpPermissions=list(wanted))


def _group(plan: Ec2NetworkPlan, wanted: Ec2GroupIntent, ec2: BaseClient) -> str:
    """Converge and independently read back a range-owned security group."""
    filters = [
        {"Name": "vpc-id", "Values": [plan.config.vpc_id]},
        {"Name": "group-name", "Values": [wanted.resource_name]},
    ]
    rows = _rows(ec2.describe_security_groups(Filters=filters), "SecurityGroups")
    if not rows:
        try:
            ec2.create_security_group(
                VpcId=plan.config.vpc_id,
                GroupName=wanted.resource_name,
                Description="Range-owned guest transport",
                TagSpecifications=[{"ResourceType": "security-group", "Tags": plan.tags(wanted.address)}],
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvalidGroup.Duplicate":
                raise
        rows = _eventually(
            lambda: _created_rows(
                ec2.describe_security_groups(Filters=filters),
                "SecurityGroups",
                "EC2 security group creation is not yet observable",
            )
        )
    group = rows[0]
    _owned(group, plan, wanted.address)
    if group.get("VpcId") != plan.config.vpc_id or group.get("GroupName") != wanted.resource_name:
        raise Ec2NetworkError("EC2 security group differs from its intended placement")
    # Remove the AWS-created universal egress grant before any VM can attach.
    _rules(ec2, group, "egress", wanted.egress)
    _rules(ec2, group, "ingress", wanted.ingress)
    _eventually(lambda: _verify_group(plan, wanted, group["GroupId"], ec2))
    return group["GroupId"]


def _verify_group(plan: Ec2NetworkPlan, wanted: Ec2GroupIntent, group_id: str, ec2: BaseClient) -> None:
    """Read back a converged security group's exact grants (read-only)."""
    observed = _rows(ec2.describe_security_groups(GroupIds=[group_id]), "SecurityGroups")
    if not observed:
        raise Ec2NetworkNotObservable("EC2 security group readback is unavailable")
    _owned(observed[0], plan, wanted.address)
    if _permissions(observed[0].get("IpPermissions", [])) != _permissions(wanted.ingress) or _permissions(
        observed[0].get("IpPermissionsEgress", [])
    ) != _permissions(wanted.egress):
        raise Ec2NetworkNotObservable("EC2 security group rules differ from the admitted plan")


def _route_table(plan: Ec2NetworkPlan, subnets: dict[str, str], routes: dict[str, str], ec2: BaseClient) -> str:
    """Attach range subnets only to the admitted private routing table."""
    subject = "backend.ec2.route-table"
    filters = [
        {"Name": "vpc-id", "Values": [plan.config.vpc_id]},
        *[
            {"Name": f"tag:{item['Key']}", "Values": [item["Value"]]}
            for item in plan.tags(subject)
            if item["Key"] != "shifter:generation"
        ],
    ]
    rows = _rows(ec2.describe_route_tables(Filters=filters), "RouteTables")
    if not rows:
        ec2.create_route_table(
            VpcId=plan.config.vpc_id, TagSpecifications=[{"ResourceType": "route-table", "Tags": plan.tags(subject)}]
        )
        rows = _eventually(
            lambda: _created_rows(
                ec2.describe_route_tables(Filters=filters),
                "RouteTables",
                "EC2 route table creation is not yet observable",
            )
        )
    row = rows[0]
    _owned(row, plan, subject)
    if row.get("VpcId") != plan.config.vpc_id:
        raise Ec2NetworkError("EC2 route table is outside the admitted network")
    _apply_routes(plan, row, subnets, routes, ec2)
    _eventually(lambda: _verify_routes(plan, subnets, routes, row["RouteTableId"], ec2))
    return row["RouteTableId"]


def _apply_routes(
    plan: Ec2NetworkPlan,
    row: dict[str, Any],
    subnets: dict[str, str],
    routes: dict[str, str],
    ec2: BaseClient,
) -> None:
    """Converge private routes and reject existing associations outside this range."""
    existing = set()
    for route in row.get("Routes", []):
        cidr = route.get("DestinationCidrBlock")
        if route.get("GatewayId") == "local" and cidr == plan.config.vpc_cidr:
            continue
        if cidr not in routes or route.get("VpcPeeringConnectionId") != routes[cidr] or route.get("State") != "active":
            raise Ec2NetworkError("EC2 owned route table contains an unadmitted destination")
        existing.add(cidr)
    for cidr in sorted(set(routes) - existing):
        ec2.create_route(
            RouteTableId=row["RouteTableId"], DestinationCidrBlock=cidr, VpcPeeringConnectionId=routes[cidr]
        )
    _associate_subnets(row, subnets, ec2)


def _associate_subnets(row: dict[str, Any], subnets: dict[str, str], ec2: BaseClient) -> None:
    """Attach only owned subnets without replacing another explicit route association."""
    associated = set()
    for association in row.get("Associations", []):
        if association.get("Main") or association.get("SubnetId") not in subnets.values():
            raise Ec2NetworkError("EC2 range route table is associated outside its range")
        associated.add(association["SubnetId"])
    for subnet_id in sorted(set(subnets.values()) - associated):
        attached = _rows(
            ec2.describe_route_tables(Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]),
            "RouteTables",
        )
        if attached and attached[0].get("RouteTableId") != row["RouteTableId"]:
            raise Ec2NetworkError("EC2 subnet is explicitly associated with another route table")
        ec2.associate_route_table(RouteTableId=row["RouteTableId"], SubnetId=subnet_id)


def _verify_routes(
    plan: Ec2NetworkPlan, subnets: dict[str, str], routes: dict[str, str], table_id: str, ec2: BaseClient
) -> None:
    """Verify exact routing and association coverage after network convergence."""
    rows = _rows(ec2.describe_route_tables(RouteTableIds=[table_id]), "RouteTables")
    if not rows:
        raise Ec2NetworkNotObservable("EC2 route table readback is unavailable")
    row = rows[0]
    _owned(row, plan, "backend.ec2.route-table")
    expected = {(plan.config.vpc_cidr, "local"), *routes.items()}
    observed = {
        (route.get("DestinationCidrBlock"), route.get("VpcPeeringConnectionId") or route.get("GatewayId"))
        for route in row.get("Routes", [])
        if route.get("State") == "active"
    }
    _verify_associations(row.get("Associations", []), subnets)
    if (
        row.get("RouteTableId") != table_id
        or row.get("VpcId") != plan.config.vpc_id
        or observed != expected
        or len(row.get("Routes", [])) != len(expected)
    ):
        raise Ec2NetworkNotObservable("EC2 route table readback differs from the admitted network")


def _verify_associations(associations: list[dict[str, Any]], subnets: dict[str, str]) -> None:
    """Require exactly one settled association for each admitted subnet."""
    if (
        {item.get("SubnetId") for item in associations} != set(subnets.values())
        or len(associations) != len(subnets)
        or any(
            item.get("Main") or item.get("AssociationState", {}).get("State") != "associated" for item in associations
        )
    ):
        raise Ec2NetworkNotObservable("EC2 route table readback differs from the admitted network")


def ensure_ec2_network(plan: Ec2NetworkPlan, ec2: BaseClient) -> Ec2NetworkResources:
    """Validate base routing before mutations, then converge only tagged ownership."""
    vpcs = _rows(ec2.describe_vpcs(VpcIds=[plan.config.vpc_id]), "Vpcs")
    if (
        not vpcs
        or vpcs[0].get("VpcId") != plan.config.vpc_id
        or vpcs[0].get("CidrBlock") != plan.config.vpc_cidr
        or vpcs[0].get("State") != "available"
        or vpcs[0].get("IsDefault")
    ):
        raise Ec2NetworkError("EC2 range VPC differs from deployment-owned identity")
    routes = peer_routes(plan.config, ec2)
    subnets = {wanted.address: _subnet(plan, wanted, ec2) for wanted in plan.subnets}
    route_table = _route_table(plan, subnets, routes, ec2)
    groups = {wanted.address: _group(plan, wanted, ec2) for wanted in plan.groups}
    return Ec2NetworkResources(subnets, groups, route_table)
