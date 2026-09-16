"""Firewall planning for GCE-backed range cells."""

from __future__ import annotations

import ipaddress
import os

from config import GCERangeCellConfig
from gcp_range_cell_model_broker import admitted_broker_destination
from gcp_range_cell_naming import _network_tag, _short_resource_name
from gcp_range_cell_types import (
    DEFAULT_GCE_EGRESS_POLICY,
    FirewallPlan,
    GceEgressPolicy,
    InstancePlan,
    OpenVpnGatewayPlan,
    SubnetPlan,
)

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


def _ipv4_complement(excluded: list[ipaddress.IPv4Network]) -> list[str]:
    """Return routable IPv4 space with every excluded network removed.

    The universal range minus the excluded set, expressed as the minimal list of
    CIDRs. Used both for the public-internet source complement (VPN ingress) and
    for the sanctioned public-web egress destination, so neither lane can name an
    excluded (internal/special-use/deployment-owned) destination by construction
    rather than by relying on rule-precedence order.

    The exclusion set is collapsed into a minimal disjoint set before subtraction.
    Without collapsing, an earlier exclusion can split a later, broader exclusion
    across fragments so the broader one is subnet_of no single remaining fragment
    and is never removed (for instance the Google VIP /30 processed before a
    declared public management /24 that contains it). Collapsing merges
    contained/overlapping/adjacent networks so every subtraction is exact.
    """
    allowed: list[ipaddress.IPv4Network] = [ipaddress.IPv4Network(_UNIVERSAL_IPV4_CIDR)]
    for excluded_network in ipaddress.collapse_addresses(excluded):
        next_allowed: list[ipaddress.IPv4Network] = []
        for network in allowed:
            if excluded_network.subnet_of(network):
                next_allowed.extend(network.address_exclude(excluded_network))
            else:
                next_allowed.append(network)
        allowed = next_allowed
    return [str(network) for network in sorted(allowed, key=lambda item: (int(item.network_address), item.prefixlen))]


def _public_ipv4_source_ranges() -> list[str]:
    """Return routable public IPv4 space without private/reserved sources."""
    return _ipv4_complement(list(_NON_PUBLIC_IPV4_CIDRS))


def _denied_egress_networks(config: GCERangeCellConfig) -> list[ipaddress.IPv4Network]:
    """ADR-056-R4 denied-network inventory for range-cell egress.

    The complete set of destinations a compromised range guest must never reach
    through a sanctioned egress lane, assembled once and reused by the public-web
    egress complement and the operator allow-CIDR overlap check so a new
    management network is excluded from both by a single edit:

    - IANA special-use space (``_NON_PUBLIC_IPV4_CIDRS``), which subsumes every
      RFC1918 deployment-owned range (platform pod/service/node, control-plane,
      portal, private-service, operator/runner, retained GDC management, and peer
      range subnets are all RFC1918) plus link-local metadata (169.254.0.0/16);
    - the Google private-API VIP (a public-IP but deployment-only special
      destination reachable only through the sanctioned Private Google Access
      lane); and
    - the explicitly declared deployment-owned management/access CIDRs carried on
      the range config (Terraform-derived via the runtime env), so a
      non-RFC1918 management network would still be covered.
    """
    denied: dict[str, ipaddress.IPv4Network] = {str(net): net for net in _NON_PUBLIC_IPV4_CIDRS}
    vip = ipaddress.ip_network(_GOOGLE_PRIVATE_API_VIP_CIDR)
    if isinstance(vip, ipaddress.IPv4Network):
        denied[str(vip)] = vip
    for values in (config.portal_network_cidrs, config.access_network_cidrs):
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            net = ipaddress.ip_network(text, strict=False)
            if isinstance(net, ipaddress.IPv4Network):
                denied[str(net)] = net
    return list(denied.values())


def _reject_denied_egress_overlap(cidrs: list[str], denied_networks: list[ipaddress.IPv4Network]) -> None:
    """Fail closed when an operator egress allow-CIDR overlaps the denied inventory.

    ADR-056-R2/R4: a sanctioned egress allow-CIDR is for public destinations only.
    Rejecting overlap with the denied-network inventory (management, peer-range,
    private-service, metadata, and special-use space) stops an allow-CIDR from
    re-opening an internal path the default deny is meant to close, instead of
    trusting firewall rule order.
    """
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr)
        for denied in denied_networks:
            if network.overlaps(denied):
                raise RuntimeError(
                    "egress_allow_cidrs must not overlap the denied-network inventory "
                    f"(management/peer-range/private-service/metadata/special-use): {network} overlaps {denied}"
                )


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


def _reject_overlapping_boundaries(access_cidrs: list[str], management_cidrs: list[str]) -> None:
    """Fail closed when access-workload and management sources overlap (#1711).

    Participant ingress (SSH/RDP) and host-management ingress must stay disjoint
    identities: an overlap would let the broad management source re-enter the
    participant path (or vice versa), defeating the dedicated access identity.
    """
    access_networks = [ipaddress.ip_network(cidr) for cidr in access_cidrs]
    management_networks = [ipaddress.ip_network(cidr) for cidr in management_cidrs]
    for access in access_networks:
        for management in management_networks:
            if access.overlaps(management):
                raise RuntimeError(
                    "access_network_cidrs must not overlap portal_network_cidrs "
                    f"(management source): {access} overlaps {management}"
                )


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
        # Dedicated access-workload source identity (#1349 / #1711): participant/
        # operator access (SSH 22, RDP 3389) is a rule of its own, sourced only
        # from the access-workload ranges (portal + guacd on the exclusive access
        # pod range), so it is never a provisioner/management wildcard.
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
    # When no access-workload range is configured we OMIT participant ingress and
    # fail closed (ADR-039-R9, #1711): loss of participant connectivity is the
    # safe failure mode. There is no fallback that opens 22/3389 to the broad
    # provisioner/management source -- that combined legacy rule is deliberately
    # gone. Management ingress below is SSH-only and never inherits RDP or
    # participant SSH.
    if portal_network_cidrs:
        # Management-only ingress: native-guest host SSH (:22) and the Docker-host
        # management sshd port (Polaris host, whose Kali container binds :22),
        # sourced from the provisioner/management range only.
        mgmt_ports = ["22"]
        if str(config.host_mgmt_ssh_port) not in mgmt_ports:
            mgmt_ports.append(str(config.host_mgmt_ssh_port))
        rules.append(_management_rule(range_id, range_tag, portal_network_cidrs, mgmt_ports))
    return rules


def _egress_rules(
    range_id: int,
    range_tag: str,
    subnet_cidrs: list[str],
    egress_allow_cidrs: list[str],
    allow_public_web_egress: bool,
    public_web_destinations: list[str],
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
    if allow_public_web_egress and public_web_destinations:
        # ADR-056-R2: sanctioned public-web egress targets the public-internet
        # complement only (0.0.0.0/0 minus the denied-network inventory), so it
        # cannot reach management, peer-range, private-service, metadata, or
        # special-use space at 80/443 -- the exclusion is structural, not a matter
        # of rule precedence against the default deny.
        rules.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-web"),
                "direction": "EGRESS",
                "priority": 1200,
                "target_tags": [range_tag],
                "destination_ranges": public_web_destinations,
                "allowed": [{"IPProtocol": "tcp", "ports": ["80", "443"]}],
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


def _public_web_egress(
    deny_general_egress: bool,
    instances: list[InstancePlan],
    include_optional_cleanup: bool,
    denied_networks: list[ipaddress.IPv4Network],
) -> tuple[bool, list[str]]:
    """Resolve the existing web lane while retaining the denied-network complement."""
    enabled = not deny_general_egress and (
        include_optional_cleanup or any(instance["profile"].allow_public_web_egress for instance in instances)
    )
    return enabled, _ipv4_complement(denied_networks) if enabled else []


def build_firewall_plan(
    range_id: int,
    subnet_plans: list[SubnetPlan],
    config: GCERangeCellConfig,
    vpn_gateway: OpenVpnGatewayPlan | None = None,
    *,
    instance_plans: list[InstancePlan] | None = None,
    include_optional_cleanup: bool = False,
    egress_policy: GceEgressPolicy = DEFAULT_GCE_EGRESS_POLICY,
) -> list[FirewallPlan]:
    """Render the firewall plan for internal range traffic and management.

    ``egress_policy.mode`` is the posture pinned on the range (PLAT-238). Both
    ``none`` (ADR-026 zero egress) and ``deny-all`` forbid general outbound egress:
    each forces the public-web-egress lane off and drops any configured allow-CIDR
    lane, so only the default egress-deny (and intra-range + Private Google Access
    management fabric, which is not a NAT path) remain. The two differ only in the
    NAT/route decision made elsewhere (``none`` carries no Cloud NAT enrollment;
    ``deny-all`` keeps a routed path behind the firewall deny). Firewall denial is
    defense in depth; it is not, by itself, the ``none`` no-NAT guarantee.
    """
    bypass = os.environ.get("GCP_RANGE_PREPROVISIONED_FIREWALLS", "").strip().lower() in {"1", "true", "yes"}
    broker_destination = admitted_broker_destination(
        egress_policy,
        config,
        subnet_plans,
        instance_plans or [],
        vpn_gateway,
        bypass,
    )
    if bypass:
        return []
    deny_general_egress = (egress_policy.mode or "status-quo").strip().lower() in {"none", "deny-all"}
    range_tag = _network_tag(range_id)
    subnet_cidrs = [subnet["cidr"] for subnet in subnet_plans]
    portal_network_cidrs = _validated_boundary_cidrs("portal_network_cidrs", config.portal_network_cidrs)
    access_network_cidrs = _validated_boundary_cidrs("access_network_cidrs", config.access_network_cidrs)
    _reject_overlapping_boundaries(access_network_cidrs, portal_network_cidrs)
    # A no-general-egress range (none/deny-all) opens no public-web lane and no
    # configured allow-CIDR lane, regardless of instance profiles or deployment
    # config.
    egress_allow_cidrs = (
        [] if deny_general_egress else _validated_boundary_cidrs("egress_allow_cidrs", config.egress_allow_cidrs)
    )
    # ADR-056-R2/R4: one denied-network inventory drives both the operator
    # allow-CIDR overlap check and the public-web egress complement, so a
    # sanctioned egress lane can never name an internal/management/metadata
    # destination.
    denied_networks = _denied_egress_networks(config)
    _reject_denied_egress_overlap(egress_allow_cidrs, denied_networks)
    allow_public_web_egress, public_web_destinations = _public_web_egress(
        deny_general_egress,
        instance_plans or [],
        include_optional_cleanup,
        denied_networks,
    )
    firewalls = _subnet_ingress_rules(range_id, subnet_plans)
    firewalls.extend(_boundary_ingress_rules(range_id, range_tag, access_network_cidrs, portal_network_cidrs, config))
    firewalls.extend(
        _egress_rules(
            range_id,
            range_tag,
            subnet_cidrs,
            egress_allow_cidrs,
            allow_public_web_egress,
            public_web_destinations,
            config,
        )
    )
    if vpn_gateway is not None:
        firewalls.extend(_vpn_gateway_rules(range_id, vpn_gateway, portal_network_cidrs))
    if broker_destination is not None:
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-model-broker"),
                "direction": "EGRESS",
                "priority": 900,
                "target_tags": [range_tag],
                "destination_ranges": [broker_destination],
                "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}],
            }
        )
    return firewalls


__all__ = ["build_firewall_plan"]
