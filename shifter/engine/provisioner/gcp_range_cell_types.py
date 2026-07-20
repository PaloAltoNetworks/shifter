"""Shared plan type contracts for GCE-backed range cells."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from config import GCERangeImageProfile

ResourceDict = dict[str, object]
ComputeResource = dict[str, object]
ScenarioInstance = ResourceDict


class NetworkPlan(TypedDict):
    """Planned Compute Engine network resource."""

    name: str
    self_link: str


class SubnetPlan(TypedDict):
    """Planned Compute Engine subnetwork resource."""

    name: str
    uuid: str
    resource_name: str
    self_link: str
    network: str
    network_link: str
    cidr: str
    region: str
    tag: str
    connected_source_ranges: list[str]
    ip_assignments: dict[str, str]
    instances: list[ScenarioInstance]


class FirewallEntry(TypedDict, total=False):
    """Compute Engine firewall allow/deny entry."""

    IPProtocol: str
    ports: list[str]


class FirewallPlan(TypedDict):
    """Planned Compute Engine firewall resource."""

    name: str
    direction: str
    priority: int
    target_tags: list[str]
    source_ranges: NotRequired[list[str]]
    destination_ranges: NotRequired[list[str]]
    allowed: NotRequired[list[FirewallEntry]]
    denied: NotRequired[list[FirewallEntry]]


class InstancePlan(TypedDict):
    """Planned Compute Engine instance and address resources."""

    name: str
    uuid: str
    resource_name: str
    address_name: str
    subnet_name: str
    subnet_resource_name: str
    subnetwork_link: str
    private_ip: str
    role: str
    os_type: str
    asset_type: str
    tags: list[str]
    profile: GCERangeImageProfile
    source: ScenarioInstance
    ssh_username: str
    host_ssh_username: str
    ssh_port: int
    participant_access_channels: list[str]
    attach_service_account: bool


class OpenVpnGatewayPlan(TypedDict):
    """Request-owned OpenVPN gateway adjacent to one Kali member."""

    resource_name: str
    address_name: str
    private_ip: str
    subnet_resource_name: str
    subnetwork_link: str
    target_ref: str
    target_ip: str
    tag: str
    profile: GCERangeImageProfile
    service_account_email: str


class RangeCellPlan(TypedDict):
    """Complete resource plan for a single GCE range cell."""

    project_id: str
    region: str
    zone: str
    request_uuid: str
    range_id: int
    private_google_access: bool
    labels: dict[str, str]
    network: NetworkPlan
    # True when the range owns its VPC (vpc-per-range) and apply/destroy must
    # create/delete it. False in shared-vpc mode, where the VPC is the pre-existing
    # platform-peered range network and only per-range subnets/firewalls are owned.
    manage_network: bool
    subnets: list[SubnetPlan]
    instances: list[InstancePlan]
    firewalls: list[FirewallPlan]
    vpn_gateway: NotRequired[OpenVpnGatewayPlan]


__all__ = [
    "ComputeResource",
    "FirewallEntry",
    "FirewallPlan",
    "InstancePlan",
    "NetworkPlan",
    "OpenVpnGatewayPlan",
    "RangeCellPlan",
    "ResourceDict",
    "ScenarioInstance",
    "SubnetPlan",
]
