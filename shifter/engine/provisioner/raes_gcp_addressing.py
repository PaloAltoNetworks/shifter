"""Static and dynamic address assignment for realized RAES GCE subnets."""

from __future__ import annotations

import ipaddress

from raes_gcp_plan_errors import RaesGcePlanError
from raes_plan import RaesPlanNetwork, RaesPlanNode


def instance_key(node: RaesPlanNode, index: int) -> str:
    """Return the stable IP-assignment key for one instance of a node."""
    return f"{node.address}#{index}"


def ip_assignments(
    network: RaesPlanNetwork,
    authored_network: RaesPlanNetwork | None,
    nodes: tuple[RaesPlanNode, ...] | list[RaesPlanNode],
    keys: list[str],
    usable: list[str],
) -> dict[str, str]:
    """Rebase authored static IPs, then fill remaining instances deterministically."""
    explicit = _explicit_assignments(network, authored_network, nodes, usable)
    available = iter(address for address in usable if address not in explicit.values())
    assignments: dict[str, str] = {}
    for key in keys:
        if key in explicit:
            assignments[key] = explicit[key]
            continue
        try:
            assignments[key] = next(available)
        except StopIteration as exc:
            raise RaesGcePlanError("GCE range subnet has too few assignable addresses") from exc
    return assignments


def _explicit_assignments(
    network: RaesPlanNetwork,
    authored_network: RaesPlanNetwork | None,
    nodes: tuple[RaesPlanNode, ...] | list[RaesPlanNode],
    usable: list[str],
) -> dict[str, str]:
    """Return the unique rebased static assignments for one subnet."""
    explicit: dict[str, str] = {}
    used: set[str] = set()
    for node in nodes:
        rebased = _rebased_static_ip(node, network, authored_network, usable)
        if rebased is None:
            continue
        if rebased in used:
            raise RaesGcePlanError("static GCE address is duplicated within its allocated network")
        explicit[instance_key(node, 0)] = rebased
        used.add(rebased)
    return explicit


def _rebased_static_ip(
    node: RaesPlanNode,
    network: RaesPlanNetwork,
    authored_network: RaesPlanNetwork | None,
    usable: list[str],
) -> str | None:
    """Return one node's authored host offset in the realized subnet."""
    requested = dict(node.network_ip_assignments).get(network.address)
    if requested is None:
        return None
    authored_cidr, realized_cidr = _static_address_context(node, network, authored_network)
    authored = _ipv4_network(authored_cidr)
    realized = _ipv4_network(realized_cidr)
    address = _ipv4_address(requested)
    if address not in authored:
        raise RaesGcePlanError("static GCE address is outside its authored network")
    rebased = str(ipaddress.IPv4Address(int(realized.network_address) + int(address) - int(authored.network_address)))
    if rebased not in usable:
        raise RaesGcePlanError("static GCE address is reserved or outside its allocated network")
    return rebased


def _static_address_context(
    node: RaesPlanNode,
    network: RaesPlanNetwork,
    authored_network: RaesPlanNetwork | None,
) -> tuple[str, str]:
    """Return the authored and realized CIDRs required for an unambiguous static IP."""
    if node.count != 1 or authored_network is None or not authored_network.cidr or not network.cidr:
        raise RaesGcePlanError("static GCE address has no unambiguous authored network")
    return authored_network.cidr, network.cidr


def _ipv4_network(value: str) -> ipaddress.IPv4Network:
    """Parse one canonical IPv4 subnet for address rebasing."""
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise RaesGcePlanError("static GCE address must use canonical IPv4 network intent") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise RaesGcePlanError("static GCE address must use IPv4")
    return network


def _ipv4_address(value: str) -> ipaddress.IPv4Address:
    """Parse one IPv4 address for address rebasing."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise RaesGcePlanError("static GCE address must use canonical IPv4 network intent") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise RaesGcePlanError("static GCE address must use IPv4")
    return address
