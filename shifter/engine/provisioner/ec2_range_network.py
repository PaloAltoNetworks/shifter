"""Pure EC2 realization of allocated portable networks and management boundaries."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from shared.model_access.network import RFC1918_IPV4_NETWORKS

from ec2_range_cleanup import Ec2CleanupScope
from raes_ec2_image import VerifiedEc2Image
from raes_plan import RaesPlan, RaesPlanNetwork, RaesPlanNode


class Ec2NetworkError(ValueError):
    """The backend cannot realize the requested topology without changing intent."""


def _network(value: str) -> ipaddress.IPv4Network:
    """Parse a canonical subnet wholly contained in private IPv4 address space."""
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except ValueError:
        raise Ec2NetworkError("EC2 network must be a canonical private IPv4 CIDR") from None
    if not any(network.subnet_of(private) for private in RFC1918_IPV4_NETWORKS):
        raise Ec2NetworkError("EC2 network must be private IPv4")
    return network


@dataclass(frozen=True)
class Ec2NetworkConfig:
    """Deployment-owned peer destinations; no default/public route is inherited."""

    environment: str
    region: str
    zone: str
    vpc_id: str
    vpc_cidr: str
    base_route_table_id: str
    management_cidrs: tuple[str, ...]
    access_cidrs: tuple[str, ...] = ()
    broker_cidrs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.environment)
            or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", self.region, flags=re.ASCII)
            or not re.fullmatch(re.escape(self.region) + r"[a-z]", self.zone)
            or not re.fullmatch(r"vpc-[0-9a-f]{8}(?:[0-9a-f]{9})?", self.vpc_id)
            or not re.fullmatch(r"rtb-[0-9a-f]{8}(?:[0-9a-f]{9})?", self.base_route_table_id)
            or not 1 <= len(self.management_cidrs) <= 16
            or len(self.access_cidrs) > 16
            or len(self.broker_cidrs) > 16
        ):
            raise Ec2NetworkError("EC2 deployment network coordinates are invalid")
        self._validate_endpoints()

    def _validate_endpoints(self) -> None:
        """Keep all platform destinations outside guest subnets and broker routes exact."""
        vpc = _network(self.vpc_cidr)
        for cidr in (*self.management_cidrs, *self.access_cidrs, *self.broker_cidrs):
            network = _network(cidr)
            if network.overlaps(vpc):
                raise Ec2NetworkError("EC2 platform endpoints must be outside the guest network")
        if any(_network(cidr).prefixlen != 32 for cidr in self.broker_cidrs):
            raise Ec2NetworkError("EC2 broker destinations must be exact private addresses")


@dataclass(frozen=True)
class Ec2SubnetIntent:
    """A reserved portable network and its opaque cloud resource name."""

    address: str
    cidr: str
    resource_name: str


@dataclass(frozen=True)
class Ec2GroupIntent:
    """Exact ingress and egress grants for a realized guest."""

    address: str
    resource_name: str
    ingress: tuple[dict[str, Any], ...]
    egress: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Ec2GuestPlacement:
    """One guest instance and its allocated private address."""

    node_address: str
    instance_key: str
    subnet_address: str
    private_ip: str


@dataclass(frozen=True)
class Ec2NetworkPlan:
    """Immutable network placement and ownership for an operation generation."""

    config: Ec2NetworkConfig
    request_id: UUID
    generation: UUID
    range_id: int
    subnets: tuple[Ec2SubnetIntent, ...]
    groups: tuple[Ec2GroupIntent, ...]
    guests: tuple[Ec2GuestPlacement, ...]

    def tags(self, subject: str) -> list[dict[str, str]]:
        values = {
            "ManagedBy": "shifter",
            "shifter:system": "shifter",
            "shifter:environment": self.config.environment,
            "shifter:request_id": str(self.request_id),
            "shifter:range_id": str(self.range_id),
            "shifter:generation": str(self.generation),
            "shifter:subject": hashlib.sha256(subject.encode()).hexdigest(),
        }
        return [{"Key": key, "Value": value} for key, value in values.items()]


def _name(range_id: int, address: str) -> str:
    """Derive a bounded opaque resource name from the range and authored address."""
    return f"shifter-r-{range_id}-{hashlib.sha256(address.encode()).hexdigest()[:24]}"


def allocation_networks(plan: RaesPlan) -> tuple[RaesPlanNetwork, ...]:
    """Open network intent receives one backend-owned network identity."""
    return plan.networks or (RaesPlanNetwork(address="backend.ec2.network.default", name="backend-default"),)


def _permission(protocol: str, cidrs: tuple[str, ...], port: int | None = None) -> dict[str, Any]:
    """Render an AWS grant with canonical unique destination CIDRs."""
    result: dict[str, Any] = {"IpProtocol": protocol, "IpRanges": [{"CidrIp": cidr} for cidr in sorted(set(cidrs))]}
    if port is not None:
        result.update(FromPort=port, ToPort=port)
    return result


def plan_ec2_network(
    plan: RaesPlan,
    *,
    config: Ec2NetworkConfig,
    scope: Ec2CleanupScope,
    allocated_cidrs: dict[str, str],
    images: dict[str, VerifiedEc2Image],
    participant_channels: dict[str, tuple[str, ...]],
    egress_mode: str,
) -> Ec2NetworkPlan:
    """Bind allocation, network selection, sizing and narrow guest security groups."""
    request_id, generation, range_id = scope.request_id, scope.generation, scope.range_id
    if (scope.environment, scope.region, scope.vpc_id) != (config.environment, config.region, config.vpc_id):
        raise Ec2NetworkError("EC2 range ownership is invalid")
    networks = _validate_network_coverage(plan, config, allocated_cidrs, images, egress_mode)
    subnets, cidrs = _plan_subnets(networks, allocated_cidrs, config, range_id)
    guests: list[Ec2GuestPlacement] = []
    groups = []
    used = {network.address: 4 for network in networks}
    for node in plan.nodes:
        placed, guest_network = _place_node(node, networks, cidrs, config, used)
        guests.extend(placed)
        if len(guests) > 256:
            raise Ec2NetworkError("EC2 guest count exceeds the realization bound")
        groups.append(
            _group_for_node(
                node,
                guest_network,
                config,
                images[node.address],
                tuple(str(net) for net in cidrs.values()),
                participant_channels.get(node.address, ()),
                range_id,
            )
        )
    return Ec2NetworkPlan(config, request_id, generation, range_id, tuple(subnets), tuple(groups), tuple(guests))


def _validate_network_coverage(
    plan: RaesPlan,
    config: Ec2NetworkConfig,
    allocated_cidrs: dict[str, str],
    images: dict[str, VerifiedEc2Image],
    egress_mode: str,
) -> tuple[RaesPlanNetwork, ...]:
    """Require exact network and image coverage under the admitted egress posture."""
    if egress_mode not in {"status-quo", "deny-all", "none"} or (egress_mode == "none" and config.broker_cidrs):
        raise Ec2NetworkError("EC2 egress posture does not admit the requested broker exception")
    networks = allocation_networks(plan)
    if not 1 <= len(networks) <= 32 or set(allocated_cidrs) != {network.address for network in networks}:
        raise Ec2NetworkError("EC2 subnet allocation does not match the compiled networks")
    if len({node.address for node in plan.nodes}) != len(plan.nodes) or set(images) != {
        node.address for node in plan.nodes
    }:
        raise Ec2NetworkError("EC2 image inventory does not match the compiled guests")
    return networks


def _place_node(
    node: RaesPlanNode,
    networks: tuple[RaesPlanNetwork, ...],
    cidrs: dict[str, ipaddress.IPv4Network],
    config: Ec2NetworkConfig,
    used: dict[str, int],
) -> tuple[list[Ec2GuestPlacement], ipaddress.IPv4Network]:
    """Allocate every replica without crossing subnet capacity or reserved address space."""
    placed = []
    network_address = _node_network(node, networks, cidrs, config)
    guest_network = cidrs[network_address]
    if (
        type(node.count) is not int
        or node.count < 1
        or used[network_address] + node.count >= guest_network.num_addresses
    ):
        raise Ec2NetworkError("EC2 subnet cannot accommodate the authored guest count")
    for _index in range(node.count):
        placed.append(
            Ec2GuestPlacement(
                node.address,
                f"{node.address}#{_index}",
                network_address,
                str(guest_network.network_address + used[network_address]),
            )
        )
        used[network_address] += 1
    return placed, guest_network


def _node_network(
    node: RaesPlanNode,
    networks: tuple[RaesPlanNetwork, ...],
    cidrs: dict[str, ipaddress.IPv4Network],
    config: Ec2NetworkConfig,
) -> str:
    """Choose the sole admitted primary network and enforce internal-network egress."""
    if node.acls:
        raise Ec2NetworkError("EC2 security groups cannot realize ordered node ACLs")
    if len(node.network_addresses) == 1 and node.network_addresses[0] in cidrs:
        network_address = node.network_addresses[0]
    elif not node.network_addresses and node.network_selection_open:
        network_address = networks[0].address
    else:
        raise Ec2NetworkError("EC2 requires one declared or open primary network per guest")
    if any(net.internal and net.address == network_address for net in networks) and config.broker_cidrs:
        raise Ec2NetworkError("An internal EC2 network cannot receive broker egress")
    return network_address


def _plan_subnets(
    networks: tuple[RaesPlanNetwork, ...],
    allocated_cidrs: dict[str, str],
    config: Ec2NetworkConfig,
    range_id: int,
) -> tuple[list[Ec2SubnetIntent], dict[str, ipaddress.IPv4Network]]:
    """Preserve authored addressing while binding exact nonoverlapping reservations."""
    subnets = []
    cidrs: dict[str, ipaddress.IPv4Network] = {}
    for network in networks:
        allocated = _network(allocated_cidrs[network.address])
        if (
            not allocated.subnet_of(_network(config.vpc_cidr))
            or not 16 <= allocated.prefixlen <= 28
            or any(allocated.overlaps(other) for other in cidrs.values())
            or (network.cidr is not None and network.cidr != str(allocated))
            or network.gateway is not None
        ):
            raise Ec2NetworkError("EC2 allocation cannot substitute authored network addressing")
        cidrs[network.address] = allocated
        subnets.append(Ec2SubnetIntent(network.address, str(allocated), _name(range_id, network.address)))
    return subnets, cidrs


def _group_for_node(
    node: RaesPlanNode,
    network: ipaddress.IPv4Network,
    config: Ec2NetworkConfig,
    image: VerifiedEc2Image,
    range_cidrs: tuple[str, ...],
    channels: tuple[str, ...],
    range_id: int,
) -> Ec2GroupIntent:
    """Render service/participant access independently of management authority."""
    ingress = [
        _permission("-1", (str(network),)),
        _permission("tcp", config.management_cidrs, image.management_ssh_port),
    ]
    for channel in channels:
        if channel not in {"ssh", "rdp"} or not config.access_cidrs:
            raise Ec2NetworkError("EC2 participant access requires an admitted channel and source network")
        ingress.append(_permission("tcp", config.access_cidrs, 22 if channel == "ssh" else 3389))
    ingress.extend(_service_grants(node, range_cidrs))
    egress = [_permission("-1", range_cidrs)]
    if config.broker_cidrs:
        egress.append(_permission("tcp", config.broker_cidrs, 443))
    # Collapse exact-duplicate grants (e.g. two participants sharing one channel both
    # yield tcp/22 from the access CIDRs): AWS rejects a permission that appears more
    # than once in a single authorize call ("The same permission must not appear
    # multiple times"). The readback comparison is set-based, so this stays consistent.
    ingress = _dedupe_permissions(ingress)
    egress = _dedupe_permissions(egress)
    if sum(len(rule["IpRanges"]) for rule in ingress) > 60:
        raise Ec2NetworkError("EC2 security group ingress exceeds the rule budget")
    return Ec2GroupIntent(node.address, _name(range_id, node.address), tuple(ingress), tuple(egress))


def _dedupe_permissions(permissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact-duplicate IP permissions, preserving order (AWS forbids repeats)."""
    unique: list[dict[str, Any]] = []
    for permission in permissions:
        if permission not in unique:
            unique.append(permission)
    return unique


def _service_grants(node: RaesPlanNode, range_cidrs: tuple[str, ...]) -> list[dict[str, Any]]:
    """Validate authored TCP/UDP service ports before rendering range-only ingress."""
    ingress = []
    for service in node.services:
        if service.protocol not in {"tcp", "udp"} or type(service.port) is not int or not 1 <= service.port <= 65535:
            raise Ec2NetworkError("EC2 service port cannot be realized")
        ingress.append(_permission(service.protocol, range_cidrs, service.port))
    return ingress
