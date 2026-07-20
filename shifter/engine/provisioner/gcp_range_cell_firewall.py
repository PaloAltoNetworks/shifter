"""Firewall planning for GCE-backed range cells."""

from __future__ import annotations

import ipaddress

from config import GCERangeCellConfig
from gcp_range_cell_naming import _network_tag, _short_resource_name
from gcp_range_cell_types import FirewallPlan, OpenVpnGatewayPlan, SubnetPlan

# private.googleapis.com VIP range. Private Google Access on the range subnet,
# the range VPC's private-googleapis DNS zone, and a route for this /30 (all in
# the range VPC Terraform) let no-external-IP guests reach Google APIs over
# Google's internal fabric. This is the only egress hole the range opens when
# private_google_access is set, so guests reach Vertex AI / Cloud Storage /
# Secret Manager while staying off the general internet.
_GOOGLE_PRIVATE_API_VIP_CIDR = "199.36.153.8/30"  # NOSONAR

_UNIVERSAL_IPV4_CIDR = "0.0.0.0/0"

# IANA special-use IPv4 space (RFC 6890 and friends) subtracted from the
# universal range to compute the public-internet complement used as the VPN
# ingress source list. These are protocol constants by definition; the S1313
# hardcoded-IP review conclusion is: safe, intentionally constant.
_NON_PUBLIC_IPV4_CIDRS: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in (
        # "this network", loopback, and the three TEST-NET documentation ranges
        # sit between the suppression-annotated entries: RFC 1918 private,
        # shared address space (RFC 6598), link-local, IETF protocol
        # assignments, 6to4 anycast, benchmarking, multicast, and reserved.
        "0.0.0.0/8",
        "10.0.0.0/8",  # NOSONAR(S1313)
        "100.64.0.0/10",  # NOSONAR(S1313)
        "127.0.0.0/8",
        "169.254.0.0/16",  # NOSONAR(S1313)
        "172.16.0.0/12",  # NOSONAR(S1313)
        "192.0.0.0/24",  # NOSONAR(S1313)
        "192.0.2.0/24",
        "192.88.99.0/24",  # NOSONAR(S1313)
        "192.168.0.0/16",  # NOSONAR(S1313)
        "198.18.0.0/15",  # NOSONAR(S1313)
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",  # NOSONAR(S1313)
        "240.0.0.0/4",  # NOSONAR(S1313)
    )
)


def _public_ipv4_source_ranges() -> list[str]:
    """Return routable public IPv4 space without private/reserved sources."""
    allowed: list[ipaddress.IPv4Network] = [ipaddress.IPv4Network(_UNIVERSAL_IPV4_CIDR)]
    for excluded in _NON_PUBLIC_IPV4_CIDRS:
        next_allowed: list[ipaddress.IPv4Network] = []
        for network in allowed:
            if excluded.subnet_of(network):
                next_allowed.extend(network.address_exclude(excluded))
            else:
                next_allowed.append(network)
        allowed = next_allowed
    return [str(network) for network in sorted(allowed, key=lambda item: (int(item.network_address), item.prefixlen))]


def _validated_boundary_cidrs(field: str, values: tuple[str, ...]) -> list[str]:
    """Return normalized explicit IPv4 boundary exceptions, rejecting universal allows."""
    normalized: list[str] = []
    for value in values:
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as exc:
            raise RuntimeError(f"{field} contains an invalid network: {value}") from exc
        if not isinstance(network, ipaddress.IPv4Network):
            raise RuntimeError(f"{field} must contain only IPv4 networks")
        if network.prefixlen == 0:
            raise RuntimeError(f"{field} must not include {_UNIVERSAL_IPV4_CIDR}")
        cidr = str(network)
        if cidr not in normalized:
            normalized.append(cidr)
    return normalized


def _subnet_ingress_rules(range_id: int, subnet_plans: list[SubnetPlan]) -> list[FirewallPlan]:
    """Allow declared peer-subnet traffic into each range subnet."""
    return [
        {
            "name": _short_resource_name("shifter-r", range_id, subnet["name"], "ingress"),
            "direction": "INGRESS",
            "priority": 1000,
            "target_tags": [subnet["tag"]],
            "source_ranges": subnet["connected_source_ranges"],
            "allowed": [{"IPProtocol": "all"}],
        }
        for subnet in subnet_plans
    ]


def _management_rule(range_id: int, range_tag: str, source_ranges: list[str], ports: list[str]) -> FirewallPlan:
    """Render the management ingress rule shared by both boundary layouts."""
    return {
        "name": _short_resource_name("shifter-r", range_id, "mgmt"),
        "direction": "INGRESS",
        "priority": 900,
        "target_tags": [range_tag],
        "source_ranges": source_ranges,
        "allowed": [{"IPProtocol": "tcp", "ports": ports}],
    }


def _boundary_ingress_rules(
    range_id: int,
    range_tag: str,
    access_network_cidrs: list[str],
    portal_network_cidrs: list[str],
    config: GCERangeCellConfig,
) -> list[FirewallPlan]:
    """Render participant-access and management ingress from platform networks."""
    rules: list[FirewallPlan] = []
    if access_network_cidrs:
        # Dedicated access-workload source identity (issue #1349): participant/
        # operator access (SSH 22, RDP 3389) is a rule of its own, sourced only
        # from the access-workload ranges (portal + guacd), so it is never a
        # provisioner/management wildcard. Provisioner + native/Docker-host
        # management ingress is the separate rule below on portal_network_cidrs.
        rules.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "access"),
                "direction": "INGRESS",
                "priority": 900,
                "target_tags": [range_tag],
                "source_ranges": access_network_cidrs,
                "allowed": [{"IPProtocol": "tcp", "ports": ["22", "3389"]}],
            }
        )
        if portal_network_cidrs:
            # Management-only ingress: native-guest host SSH (:22) and the
            # Docker-host management sshd port (Polaris host, whose Kali container
            # binds :22). No RDP: participant RDP is the access rule above.
            mgmt_ports = ["22"]
            if str(config.host_mgmt_ssh_port) not in mgmt_ports:
                mgmt_ports.append(str(config.host_mgmt_ssh_port))
            rules.append(_management_rule(range_id, range_tag, portal_network_cidrs, mgmt_ports))
    elif portal_network_cidrs:
        # No dedicated access-workload range configured: keep the legacy combined
        # rule (SSH participant + native-guest host, RDP, Docker-host sshd) so
        # deployments without an access node pool are unchanged.
        mgmt_ports = ["22", "3389"]
        if str(config.host_mgmt_ssh_port) not in mgmt_ports:
            mgmt_ports.append(str(config.host_mgmt_ssh_port))
        rules.append(_management_rule(range_id, range_tag, portal_network_cidrs, mgmt_ports))
    return rules


def _egress_rules(
    range_id: int,
    range_tag: str,
    subnet_cidrs: list[str],
    egress_allow_cidrs: list[str],
    config: GCERangeCellConfig,
) -> list[FirewallPlan]:
    """Render intra-range egress, the default deny, and configured exceptions."""
    rules: list[FirewallPlan] = [
        {
            "name": _short_resource_name("shifter-r", range_id, "egress-internal"),
            "direction": "EGRESS",
            "priority": 1000,
            "target_tags": [range_tag],
            "destination_ranges": subnet_cidrs,
            "allowed": [{"IPProtocol": "all"}],
        },
        {
            "name": _short_resource_name("shifter-r", range_id, "egress-deny"),
            "direction": "EGRESS",
            "priority": 65534,
            "target_tags": [range_tag],
            "destination_ranges": [_UNIVERSAL_IPV4_CIDR],
            "denied": [{"IPProtocol": "all"}],
        },
    ]
    if egress_allow_cidrs:
        rules.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-allow"),
                "direction": "EGRESS",
                "priority": 1100,
                "target_tags": [range_tag],
                "destination_ranges": egress_allow_cidrs,
                "allowed": [{"IPProtocol": "all"}],
            }
        )
    if config.private_google_access:
        # Couple Private Google Access with its egress hole automatically: with
        # PGA the range VPC resolves *.googleapis.com to the private VIP and
        # routes it internally, but the per-range egress-deny still blocks it
        # without this allow. Guests reach Vertex AI (a14-kali agent), Cloud
        # Storage (smoketest tarball), and Secret Manager (per-range Vertex key)
        # over HTTPS to the VIP only, staying off the general internet.
        rules.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-googleapis"),
                "direction": "EGRESS",
                "priority": 1100,
                "target_tags": [range_tag],
                "destination_ranges": [_GOOGLE_PRIVATE_API_VIP_CIDR],
                "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}],
            }
        )
    return rules


def _vpn_gateway_rules(
    range_id: int,
    vpn_gateway: OpenVpnGatewayPlan,
    portal_network_cidrs: list[str],
) -> list[FirewallPlan]:
    """Render the closed ingress/egress envelope for the OpenVPN gateway."""
    return [
        {
            "name": _short_resource_name("shifter-r", range_id, "vpn-in"),
            "direction": "INGRESS",
            "priority": 800,
            "target_tags": [vpn_gateway["tag"]],
            "source_ranges": _public_ipv4_source_ranges(),
            "allowed": [{"IPProtocol": "udp", "ports": ["1194"]}],
        },
        {
            "name": _short_resource_name("shifter-r", range_id, "vpn-health"),
            "direction": "INGRESS",
            "priority": 800,
            "target_tags": [vpn_gateway["tag"]],
            "source_ranges": portal_network_cidrs,
            "allowed": [{"IPProtocol": "tcp", "ports": ["1195"]}],
        },
        {
            "name": _short_resource_name("shifter-r", range_id, "vpn-target"),
            "direction": "EGRESS",
            "priority": 800,
            "target_tags": [vpn_gateway["tag"]],
            "destination_ranges": [f"{vpn_gateway['target_ip']}/32"],
            "allowed": [{"IPProtocol": "all"}],
        },
        {
            "name": _short_resource_name("shifter-r", range_id, "vpn-api"),
            "direction": "EGRESS",
            "priority": 800,
            "target_tags": [vpn_gateway["tag"]],
            "destination_ranges": [_GOOGLE_PRIVATE_API_VIP_CIDR],
            "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}],
        },
        {
            "name": _short_resource_name("shifter-r", range_id, "vpn-deny"),
            "direction": "EGRESS",
            "priority": 900,
            "target_tags": [vpn_gateway["tag"]],
            "destination_ranges": [_UNIVERSAL_IPV4_CIDR],
            "denied": [{"IPProtocol": "all"}],
        },
    ]


def build_firewall_plan(
    range_id: int,
    subnet_plans: list[SubnetPlan],
    config: GCERangeCellConfig,
    vpn_gateway: OpenVpnGatewayPlan | None = None,
) -> list[FirewallPlan]:
    """Render the firewall plan for internal range traffic and management."""
    range_tag = _network_tag(range_id)
    subnet_cidrs = [subnet["cidr"] for subnet in subnet_plans]
    portal_network_cidrs = _validated_boundary_cidrs("portal_network_cidrs", config.portal_network_cidrs)
    access_network_cidrs = _validated_boundary_cidrs("access_network_cidrs", config.access_network_cidrs)
    egress_allow_cidrs = _validated_boundary_cidrs("egress_allow_cidrs", config.egress_allow_cidrs)
    firewalls = _subnet_ingress_rules(range_id, subnet_plans)
    firewalls.extend(_boundary_ingress_rules(range_id, range_tag, access_network_cidrs, portal_network_cidrs, config))
    firewalls.extend(_egress_rules(range_id, range_tag, subnet_cidrs, egress_allow_cidrs, config))
    if vpn_gateway is not None:
        firewalls.extend(_vpn_gateway_rules(range_id, vpn_gateway, portal_network_cidrs))
    return firewalls


__all__ = ["build_firewall_plan"]
