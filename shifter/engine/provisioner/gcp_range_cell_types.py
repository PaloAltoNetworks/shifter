"""Shared plan type contracts for GCE-backed range cells."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from config import GCERangeImageProfile

ResourceDict = dict[str, object]
ComputeResource = dict[str, object]
ScenarioInstance = ResourceDict


@dataclass(frozen=True)
class GceEgressPolicy:
    """Pinned egress posture and separately admitted broker capability.

    Mode uses the existing range-egress vocabulary. The broker capability is
    never inferred from deployment enablement or a configured VIP.
    """

    mode: str = "status-quo"
    model_broker: dict[str, object] | None = None


DEFAULT_GCE_EGRESS_POLICY = GceEgressPolicy()


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
    image_key: str
    image_profile_fingerprint: str
    source: ScenarioInstance
    ssh_username: str
    host_ssh_username: str
    ssh_port: int
    participant_access_channels: list[str]
    # Resolved per-channel participant login names (#1710). Non-secret
    # realization metadata, kept per channel because an RAES scenario may broker
    # SSH and RDP as different authored accounts; the cyberscript path leaves it
    # empty and keeps using the instance-wide ``ssh_username``.
    participant_access_usernames: NotRequired[dict[str, str]]
    attach_service_account: bool
    # Exact identity selected from a bounded pool for profiles that cannot use
    # the deployment-wide range-host identity.
    service_account_email: NotRequired[str]


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
    # Range-owned Cloud Router + Cloud NAT (PLAT-238, ADR-026-R6). Present only for
    # a non-`none` range: it gives that range's participant subnets an explicit,
    # range-scoped NAT egress path instead of the deprecated shared all-subnet NAT.
    # A `none` (zero-egress) range omits it entirely, so its subnets carry no NAT
    # path at all -- a firewall deny alone is not that guarantee.
    router_nat: NotRequired[RouterNatPlan]


class RouterNatPlan(TypedDict):
    """A range-owned Cloud Router carrying a Cloud NAT scoped to this range's subnets."""

    router_name: str
    nat_name: str
    # self_links of the range subnets this NAT covers (LIST_OF_SUBNETWORKS scope).
    subnetwork_self_links: list[str]


__all__ = [
    "ComputeResource",
    "FirewallEntry",
    "FirewallPlan",
    "InstancePlan",
    "NetworkPlan",
    "OpenVpnGatewayPlan",
    "RangeCellPlan",
    "ResourceDict",
    "RouterNatPlan",
    "ScenarioInstance",
    "SubnetPlan",
]
