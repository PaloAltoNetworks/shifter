"""Provisioner-side parsing for authored RAES static network addresses."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

from raes_plan_types import RaesPlanError, RaesPlanNetwork
from raes_plan_values import _infrastructure_spec


def network_ip_assignments(
    node_address: str,
    payload: Mapping[str, Any],
    network_lookup: Mapping[str, str],
    network_by_address: Mapping[str, RaesPlanNetwork],
    resolved_networks: tuple[str, ...],
    count: int,
) -> tuple[tuple[str, str], ...]:
    """Read the exact RAES 3.5 static-address property shape, fail closed."""
    assignments: list[tuple[str, str]] = []
    raw = _infrastructure_spec(payload).get("properties")
    if raw in (None, []):
        return tuple(assignments)
    entry = _single_property_entry(node_address, raw, count)
    network_address, value = _resolved_property(
        node_address,
        entry,
        network_lookup,
        resolved_networks,
    )
    address = _ipv4_address(node_address, value)
    authored = _authored_network(node_address, network_by_address[network_address])
    _validate_assignable(node_address, address, authored)
    assignments.append((network_address, str(address)))
    return tuple(assignments)


def _single_property_entry(node_address: str, raw: object, count: int) -> Mapping[str, object]:
    """Return one well-formed network property entry for a singleton node."""
    if not isinstance(raw, list | tuple):
        raise RaesPlanError(f"node {node_address} network properties must be a list")
    if count != 1:
        raise RaesPlanError(f"node {node_address} with a static network address must have count 1")
    if len(raw) != 1:
        raise RaesPlanError(f"node {node_address} static address must uniquely target its primary network")
    entry = raw[0]
    if not isinstance(entry, Mapping) or len(entry) != 1:
        raise RaesPlanError(f"node {node_address} network property must name one network and IPv4 address")
    return entry


def _resolved_property(
    node_address: str,
    entry: Mapping[str, object],
    network_lookup: Mapping[str, str],
    resolved_networks: tuple[str, ...],
) -> tuple[str, str]:
    """Resolve one property to the node's canonical primary network."""
    ref, value = next(iter(entry.items()))
    if not isinstance(ref, str) or not ref.strip() or not isinstance(value, str) or not value.strip():
        raise RaesPlanError(f"node {node_address} network property must name one network and IPv4 address")
    network_address = network_lookup.get(ref)
    if network_address is None or network_address not in resolved_networks:
        raise RaesPlanError(f"node {node_address} static address references an unknown or unattached network")
    if not resolved_networks or network_address != resolved_networks[0]:
        raise RaesPlanError(f"node {node_address} static address must target its primary network")
    return network_address, value.strip()


def _ipv4_address(node_address: str, value: str) -> ipaddress.IPv4Address:
    """Parse one authored IPv4 address."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise RaesPlanError(f"node {node_address} static network address must be IPv4") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise RaesPlanError(f"node {node_address} static network address must be IPv4")
    return address


def _authored_network(node_address: str, network: RaesPlanNetwork) -> ipaddress.IPv4Network:
    """Parse the canonical authored IPv4 network for a static address."""
    if not network.cidr:
        raise RaesPlanError(f"node {node_address} static address requires an authored network CIDR")
    try:
        authored = ipaddress.ip_network(network.cidr, strict=True)
    except ValueError as exc:
        raise RaesPlanError(f"node {node_address} static address requires a canonical IPv4 network") from exc
    if not isinstance(authored, ipaddress.IPv4Network):
        raise RaesPlanError(f"node {node_address} static address must belong to its authored IPv4 network")
    return authored


def _validate_assignable(
    node_address: str,
    address: ipaddress.IPv4Address,
    authored: ipaddress.IPv4Network,
) -> None:
    """Require a provider-assignable host within the authored subnet."""
    if address not in authored:
        raise RaesPlanError(f"node {node_address} static address must belong to its authored IPv4 network")
    offset = int(address) - int(authored.network_address)
    if offset < 3 or offset > authored.num_addresses - 4:
        raise RaesPlanError(f"node {node_address} static address is reserved or unavailable on GCE")
