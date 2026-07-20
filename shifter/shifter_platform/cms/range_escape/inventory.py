"""Boundary-target inventory for the range-escape suite (issue #1347).

Targets are resolved from platform-owned state (network inventory, the closed
range-cell result surfaced as :class:`RangeUnderTest`, and the ADR-017 egress
policy), never from participant input. ``build_subject_targets`` produces the
probes launched from the range under test toward every outer boundary (plus a
positive control), and ``build_management_ingress_targets`` produces the
peer-sourced probes that prove a peer range cannot reach this range's management
ports.

To avoid certifying a whole boundary from one arbitrarily chosen endpoint, CIDR
boundaries are sampled across several addresses and representative ports, and
cross-range DNS is derived from peer-owned names rather than platform names.
Datagram (UDP) reachability beyond DNS name resolution is not probed; that residual
is documented in the operator runbook rather than silently assumed closed.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

from cms.range_escape.model import (
    EgressPolicy,
    PlatformInventory,
    ProbeKind,
    ProbeTarget,
    RangeUnderTest,
)
from shared.range_escape import BoundaryCode, DestinationClass, Outcome

# Representative ports probed per boundary. A single port cannot prove a CIDR is
# isolated, so each network boundary is sampled across a small port set.
_PLATFORM_PORTS: tuple[int, ...] = (443, 22, 10250)
_CROSS_RANGE_PORTS: tuple[int, ...] = (22, 443, 3389)
_EGRESS_PORTS: tuple[int, ...] = (443, 80)
_CIDR_SAMPLE_SIZE = 3


def build_subject_targets(
    *,
    subject: RangeUnderTest,
    peers: Sequence[RangeUnderTest],
    platform: PlatformInventory,
    egress: EgressPolicy,
) -> list[ProbeTarget]:
    """Return the probes launched from ``subject``'s participant context."""
    targets: list[ProbeTarget] = [_control_target(subject)]
    targets.extend(_platform_targets(platform))
    targets.append(_metadata_target(platform))
    targets.extend(_egress_targets(egress))
    if peers:
        targets.extend(_cross_range_targets(peers))
    return targets


def build_management_ingress_targets(*, subject: RangeUnderTest, peer: RangeUnderTest) -> list[ProbeTarget]:
    """Return probes launched from ``peer`` proving it cannot reach ``subject`` management ports."""
    targets: list[ProbeTarget] = []
    for member_ip in subject.member_ips:
        for port in subject.management_ports:
            targets.append(
                ProbeTarget(
                    check_id=f"core.management_ingress.peer-{peer.range_id}.{_slug(member_ip)}.{port}",
                    boundary_code=BoundaryCode.MANAGEMENT_INGRESS,
                    destination_class=DestinationClass.MANAGEMENT,
                    kind=ProbeKind.TCP_CONNECT,
                    expected=Outcome.UNREACHABLE,
                    address=member_ip,
                    port=port,
                )
            )
    return targets


def _control_target(subject: RangeUnderTest) -> ProbeTarget:
    """A positive control: the participant reaching its own SSH port must succeed.

    If it does not, the probe environment is broken and no "unreachable" result can
    be trusted, so the verdict fails closed (see ``compute_verdict``).
    """
    return ProbeTarget(
        check_id="control.probe_capability",
        boundary_code=BoundaryCode.PROBE_CONTROL,
        destination_class=DestinationClass.CONTROL,
        kind=ProbeKind.TCP_CONNECT,
        expected=Outcome.REACHABLE,
        address=subject.participant.address,
        port=subject.participant.ssh_port,
    )


def _platform_targets(platform: PlatformInventory) -> list[ProbeTarget]:
    """Return probe targets for every platform-network boundary."""
    targets: list[ProbeTarget] = []
    targets.extend(_cidr_targets(platform.pod_cidr, BoundaryCode.PLATFORM_POD_CIDR, DestinationClass.PLATFORM_POD))
    targets.extend(
        _cidr_targets(platform.service_cidr, BoundaryCode.PLATFORM_SERVICE_CIDR, DestinationClass.PLATFORM_SERVICE)
    )
    targets.extend(_cidr_targets(platform.node_cidr, BoundaryCode.PLATFORM_NODE_IP, DestinationClass.PLATFORM_NODE))
    for index, endpoint in enumerate(platform.portal_private_endpoints):
        address, port = _split_endpoint(endpoint, default_port=443)
        targets.append(
            ProbeTarget(
                check_id=f"core.platform_portal_private.{index}",
                boundary_code=BoundaryCode.PLATFORM_PORTAL_PRIVATE,
                destination_class=DestinationClass.PORTAL_PRIVATE,
                kind=ProbeKind.TCP_CONNECT,
                expected=Outcome.UNREACHABLE,
                address=address,
                port=port,
            )
        )
    if platform.gke_gdc_api_endpoint:
        address, port = _split_endpoint(platform.gke_gdc_api_endpoint, default_port=443)
        targets.append(
            ProbeTarget(
                check_id="core.gke_gdc_api",
                boundary_code=BoundaryCode.GKE_GDC_API,
                destination_class=DestinationClass.GKE_GDC_API,
                kind=ProbeKind.TCP_CONNECT,
                expected=Outcome.UNREACHABLE,
                address=address,
                port=port,
            )
        )
    for index, name in enumerate(platform.private_dns_names):
        targets.append(
            ProbeTarget(
                check_id=f"core.platform_dns.{index}",
                boundary_code=BoundaryCode.PLATFORM_DNS,
                destination_class=DestinationClass.PLATFORM_DNS,
                kind=ProbeKind.DNS_RESOLVE,
                expected=Outcome.UNREACHABLE,
                hostname=name,
            )
        )
    return targets


def _cidr_targets(cidr: str, boundary: BoundaryCode, destination: DestinationClass) -> list[ProbeTarget]:
    """Return sampled address x port probe targets for one platform CIDR boundary."""
    targets: list[ProbeTarget] = []
    for address in _cidr_sample_addresses(cidr):
        for port in _PLATFORM_PORTS:
            targets.append(
                ProbeTarget(
                    check_id=f"core.{boundary.value}.{_slug(address)}.{port}",
                    boundary_code=boundary,
                    destination_class=destination,
                    kind=ProbeKind.TCP_CONNECT,
                    expected=Outcome.UNREACHABLE,
                    address=address,
                    port=port,
                )
            )
    return targets


def _metadata_target(platform: PlatformInventory) -> ProbeTarget:
    """Build the metadata-server probe target."""
    return ProbeTarget(
        check_id="core.metadata_server",
        boundary_code=BoundaryCode.METADATA_SERVER,
        destination_class=DestinationClass.METADATA,
        kind=ProbeKind.METADATA,
        expected=Outcome.UNREACHABLE,
        address=platform.metadata_ip,
        hostname=platform.metadata_host,
    )


def _egress_targets(egress: EgressPolicy) -> list[ProbeTarget]:
    """Return internet-egress probe targets per the ADR-017 egress policy.

    Under ``allowlist``, operator-owned live canaries are expected reachable and the
    denied canaries unreachable; a policy CIDR is never probed as a live canary
    because it may hold no live host. Under ``status-quo`` the canaries are expected
    reachable; under ``deny-all``/``none`` they are expected unreachable.
    """
    if egress.mode == "allowlist":
        return _egress_ports_targets(egress.allowed_canaries, "allowed", Outcome.REACHABLE) + _egress_ports_targets(
            egress.canaries, "denied", Outcome.UNREACHABLE
        )
    if egress.mode == "status-quo":
        return _egress_ports_targets(egress.canaries, "statusquo", Outcome.REACHABLE)
    return _egress_ports_targets(egress.canaries, "denied", Outcome.UNREACHABLE)


def _egress_ports_targets(canaries: Sequence[str], label: str, expected: Outcome) -> list[ProbeTarget]:
    """Return egress targets for each canary across the representative ports."""
    targets: list[ProbeTarget] = []
    for index, canary in enumerate(canaries):
        for port in _EGRESS_PORTS:
            targets.append(_egress_target(f"core.internet_egress.{label}.{index}.{port}", canary, port, expected))
    return targets


def _egress_target(check_id: str, address: str, port: int, expected: Outcome) -> ProbeTarget:
    """Build one internet-egress probe target."""
    return ProbeTarget(
        check_id=check_id,
        boundary_code=BoundaryCode.INTERNET_EGRESS,
        destination_class=DestinationClass.INTERNET,
        kind=ProbeKind.TCP_CONNECT,
        expected=expected,
        address=address,
        port=port,
    )


def _cross_range_targets(peers: Sequence[RangeUnderTest]) -> list[ProbeTarget]:
    """Return cross-range private-IP and peer-owned DNS probe targets."""
    targets: list[ProbeTarget] = []
    for peer in peers:
        for member_ip in peer.member_ips:
            for port in _CROSS_RANGE_PORTS:
                targets.append(
                    ProbeTarget(
                        check_id=f"core.cross_range_private_ip.peer-{peer.range_id}.{_slug(member_ip)}.{port}",
                        boundary_code=BoundaryCode.CROSS_RANGE_PRIVATE_IP,
                        destination_class=DestinationClass.PEER_RANGE,
                        kind=ProbeKind.TCP_CONNECT,
                        expected=Outcome.UNREACHABLE,
                        address=member_ip,
                        port=port,
                    )
                )
        for index, name in enumerate(peer.dns_names):
            targets.append(
                ProbeTarget(
                    check_id=f"core.cross_range_dns.peer-{peer.range_id}.{index}",
                    boundary_code=BoundaryCode.CROSS_RANGE_DNS,
                    destination_class=DestinationClass.PEER_RANGE,
                    kind=ProbeKind.DNS_RESOLVE,
                    expected=Outcome.UNREACHABLE,
                    hostname=name,
                )
            )
    return targets


def _cidr_sample_addresses(cidr: str, count: int = _CIDR_SAMPLE_SIZE) -> list[str]:
    """Return up to ``count`` representative host addresses from ``cidr``.

    Samples the first, middle, and last usable host so a boundary claim does not
    rest on a single (possibly idle) address. Uses integer arithmetic so large
    CIDRs are not materialized.
    """
    network = ipaddress.ip_network(cidr, strict=False)
    if network.num_addresses == 1:
        return [str(network.network_address)]
    first = int(network.network_address) + 1
    last = int(network.broadcast_address) - 1
    if last < first:
        return [str(network.network_address)]
    middle = int(network.network_address) + network.num_addresses // 2
    candidates = [first, middle, last][:count]
    seen: list[int] = []
    for value in candidates:
        clamped = min(max(value, first), last)
        if clamped not in seen:
            seen.append(clamped)
    family = ipaddress.IPv4Address if network.version == 4 else ipaddress.IPv6Address
    return [str(family(value)) for value in seen]


def _split_endpoint(endpoint: str, *, default_port: int) -> tuple[str, int]:
    """Split a ``host:port`` endpoint, falling back to ``default_port``."""
    host, sep, port = endpoint.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return endpoint, default_port


def _slug(value: str) -> str:
    """Return a check-id-safe slug of an address (dots/colons to underscores)."""
    return value.replace(".", "_").replace(":", "_")


__all__ = ["build_management_ingress_targets", "build_subject_targets"]
