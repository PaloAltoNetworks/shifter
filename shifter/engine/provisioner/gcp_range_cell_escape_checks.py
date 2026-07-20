"""Static cross-range leak checker for rendered GCE range-cell plans (issue #1347).

This is the deterministic, no-cloud half of the escape-validation suite. It
inspects a rendered :data:`gcp_range_cell_plan.RangeCellPlan` for the firewall
anti-patterns ``gcp-range-cell-boundary-controls-preflight-1345.md`` calls out:
an ``allow`` rule whose source/destination reaches the shared range VPC beyond
this range's own subnets (a peer-range escape path in a shared VPC) or a
universal ``0.0.0.0/0`` / ``::/0`` allow. Findings carry the exact leaked
:class:`shared.range_escape.BoundaryCode`, so a misconfigured rule is caught in
tests or a fixture before it ever reaches a live range.

The live probe half of the suite proves the deployed boundary from inside the
cell; this half proves the plan that produced it. Both speak the same boundary
codes.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from shared.range_escape import BoundaryCode

_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class LeakFinding:
    """A single cross-range or over-broad allow found in a rendered plan."""

    boundary_code: BoundaryCode
    firewall_name: str
    direction: str
    cidr: str
    reason: str


def find_cross_range_leaks(plan: Mapping[str, object], *, range_network_cidr: str) -> list[LeakFinding]:
    """Return the cross-range / over-broad allow leaks in a rendered range-cell plan.

    ``range_network_cidr`` is the shared range VPC base CIDR that per-range subnets
    are carved from; a rule that allows traffic to or from address space inside
    that CIDR but outside this range's own subnets is a peer-range escape path.
    Only ``allow`` rules can leak; ``deny`` rules (including the baseline
    ``0.0.0.0/0`` egress deny) are never findings.
    """
    own_subnets = _own_subnets(plan)
    range_net = ipaddress.ip_network(range_network_cidr, strict=False)
    findings: list[LeakFinding] = []
    for firewall in _firewalls(plan):
        if not firewall.get("allowed"):
            continue
        direction = str(firewall.get("direction", ""))
        name = str(firewall.get("name", ""))
        key = "source_ranges" if direction == "INGRESS" else "destination_ranges"
        ranges = _string_list(firewall.get(key))
        if not ranges:
            # GCP defaults a source-less ingress allow and a destination-less egress
            # allow to the universal IPv4 route (0.0.0.0/0). An absent field is a
            # universal allow, not "nothing to check".
            code = BoundaryCode.INTERNET_EGRESS if direction == "EGRESS" else BoundaryCode.CROSS_RANGE_PRIVATE_IP
            findings.append(
                LeakFinding(code, name, direction, "0.0.0.0/0", "provider-default universal allow (no explicit range)")
            )
            continue
        for raw_cidr in ranges:
            finding = _classify_cidr(raw_cidr, direction, name, range_net, own_subnets)
            if finding is not None:
                findings.append(finding)
    return findings


def _classify_cidr(
    raw_cidr: str,
    direction: str,
    name: str,
    range_net: _IPNetwork,
    own_subnets: list[_IPNetwork],
) -> LeakFinding | None:
    """Classify one allow-rule CIDR as a leak (or not) for a rendered plan."""
    try:
        net = ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        return LeakFinding(
            BoundaryCode.CROSS_RANGE_PRIVATE_IP, name, direction, raw_cidr, "unparseable CIDR in allow rule"
        )
    finding: LeakFinding | None = None
    if net.prefixlen == 0:
        code = BoundaryCode.INTERNET_EGRESS if direction == "EGRESS" else BoundaryCode.CROSS_RANGE_PRIVATE_IP
        finding = LeakFinding(code, name, direction, raw_cidr, "universal allow (default route)")
    elif net.version == range_net.version and net.overlaps(range_net) and not _within_own(net, own_subnets):
        finding = LeakFinding(
            BoundaryCode.CROSS_RANGE_PRIVATE_IP,
            name,
            direction,
            raw_cidr,
            "allow reaches peer-range address space in the shared range VPC",
        )
    return finding


def _within_own(net: _IPNetwork, own_subnets: Iterable[_IPNetwork]) -> bool:
    """True when ``net`` is contained within one of this range's own subnets."""
    for subnet in own_subnets:
        if (
            isinstance(net, ipaddress.IPv4Network)
            and isinstance(subnet, ipaddress.IPv4Network)
            and net.subnet_of(subnet)
        ):
            return True
        if (
            isinstance(net, ipaddress.IPv6Network)
            and isinstance(subnet, ipaddress.IPv6Network)
            and net.subnet_of(subnet)
        ):
            return True
    return False


def _own_subnets(plan: Mapping[str, object]) -> list[_IPNetwork]:
    """Return this range's own subnet networks from a rendered plan."""
    subnets: list[_IPNetwork] = []
    raw = plan.get("subnets")
    if not isinstance(raw, list):
        return subnets
    for subnet in raw:
        if not isinstance(subnet, Mapping):
            continue
        cidr = str(subnet.get("cidr") or "").strip()
        if cidr:
            subnets.append(ipaddress.ip_network(cidr, strict=False))
    return subnets


def _firewalls(plan: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Return the firewall rule objects from a rendered plan."""
    raw = plan.get("firewalls")
    if not isinstance(raw, list):
        return []
    return [fw for fw in raw if isinstance(fw, Mapping)]


def _string_list(value: object) -> list[str]:
    """Return ``value`` as a list of strings, or an empty list."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


__all__ = ["LeakFinding", "find_cross_range_leaks"]
