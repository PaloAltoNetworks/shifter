"""Adapt portable RAES realization intent to the GCE range-cell core.

The RAE runtime owns the authoritative provisioning plan.  This module makes
only provider choices that the plan explicitly leaves open, producing a copied
backend plan for the GCE core while leaving the portable plan untouched for
completion accounting and runtime feedback.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import replace

from config import GCERangeCellConfig
from raes_plan import RaesPlan, RaesPlanNetwork

DEFAULT_NETWORK_ADDRESS = "backend.gce.network.default"
_DEFAULT_NETWORK_NAME = "backend-default"
_PRIVATE_POOL = ipaddress.IPv4Network("172.16.0.0/12")  # NOSONAR -- RFC 1918 allocation pool.
_DEFAULT_PREFIX = 28
_TEARDOWN_ONLY_NETWORK_CIDR = "198.18.0.0/16"  # NOSONAR -- RFC 2544 teardown placeholder.
_AUTHORED_NETWORK_SOURCE = "authored GCE network"


class RaesGceAdapterError(ValueError):
    """Raised when open portable intent cannot be safely bound for GCE."""


def adapt_raes_plan_for_gce(
    plan: RaesPlan,
    config: GCERangeCellConfig,
    *,
    allocated_network_cidrs: Sequence[tuple[str, str]] | None = None,
    reconstruct_for_teardown: bool = False,
) -> RaesPlan:
    """Return the GCE-core plan selected under the runtime's portable plan.

    Nodes with authored network references retain their portable intent. Nodes
    whose compiled infrastructure omits network selection share one internal
    backend subnet. Shared-VPC mode realizes every network through the tenant
    allocator; a per-range VPC can select a non-overlapping private subnet locally.
    """
    open_nodes = tuple(node for node in plan.nodes if node.network_selection_open)
    if open_nodes:
        if any(network.address == DEFAULT_NETWORK_ADDRESS for network in plan.networks):
            raise RaesGceAdapterError("portable plan collides with the reserved GCE adapter network identity")

        cidr = None if config.network_mode == "shared-vpc" else _default_network_cidr(plan, config)
        network = RaesPlanNetwork(
            address=DEFAULT_NETWORK_ADDRESS,
            name=_DEFAULT_NETWORK_NAME,
            cidr=cidr,
            internal=True,
        )
        open_addresses = {node.address for node in open_nodes}
        nodes = tuple(
            replace(node, network_addresses=(DEFAULT_NETWORK_ADDRESS,)) if node.address in open_addresses else node
            for node in plan.nodes
        )
        plan = replace(plan, nodes=nodes, networks=(*plan.networks, network))
    if config.network_mode == "shared-vpc":
        if not plan.networks:
            if allocated_network_cidrs:
                raise RaesGceAdapterError("allocated GCE network projection does not match the realized network shape")
            return plan
        return _realize_shared_vpc_networks(
            plan,
            allocated_network_cidrs,
            reconstruct_for_teardown=reconstruct_for_teardown,
        )
    if allocated_network_cidrs:
        raise RaesGceAdapterError("tenant subnet allocation is valid only in shared-VPC mode")
    return plan


def requires_allocated_gce_network(plan: RaesPlan, config: GCERangeCellConfig) -> bool:
    """Return whether this plan needs the tenant shared-VPC allocator."""
    return config.network_mode == "shared-vpc" and bool(
        plan.networks or any(node.network_selection_open for node in plan.nodes)
    )


def _default_network_cidr(
    plan: RaesPlan,
    config: GCERangeCellConfig,
) -> str:
    """Handle default network cidr."""
    occupied = _occupied_networks(plan, config)
    for candidate in _PRIVATE_POOL.subnets(new_prefix=_DEFAULT_PREFIX):
        if not any(candidate.overlaps(other) for other in occupied):
            return str(candidate)
    raise RaesGceAdapterError("no private GCE subnet is available for open network selection")


def _realize_shared_vpc_networks(
    plan: RaesPlan,
    allocated_network_cidrs: Sequence[tuple[str, str]] | None,
    *,
    reconstruct_for_teardown: bool,
) -> RaesPlan:
    """Return a copied plan whose complete network set uses one allocation projection."""
    identities = tuple(network.address for network in plan.networks)
    projection = _allocation_projection(plan, allocated_network_cidrs, reconstruct_for_teardown)
    if len(projection) != len(identities) or tuple(address for address, _cidr in projection) != identities:
        raise RaesGceAdapterError("allocated GCE network projection does not match the realized network shape")

    realized: list[RaesPlanNetwork] = []
    seen_cidrs: set[ipaddress.IPv4Network] = set()
    for authored, (_address, cidr) in zip(plan.networks, projection, strict=True):
        realized.append(_realized_network(authored, cidr, seen_cidrs))
    return replace(plan, networks=tuple(realized))


def _allocation_projection(
    plan: RaesPlan,
    allocated_network_cidrs: Sequence[tuple[str, str]] | None,
    reconstruct_for_teardown: bool,
) -> tuple[tuple[str, str], ...]:
    """Select the persisted or names-only teardown projection."""
    if allocated_network_cidrs is not None:
        return tuple(allocated_network_cidrs)
    if reconstruct_for_teardown:
        return _teardown_projection(plan.networks)
    raise RaesGceAdapterError("shared-VPC networks require a tenant-allocated subnet projection")


def _realized_network(
    authored: RaesPlanNetwork,
    cidr: str,
    seen_cidrs: set[ipaddress.IPv4Network],
) -> RaesPlanNetwork:
    """Validate and rebase one authored network into its allocated subnet."""
    candidate = _ipv4_subnet(cidr, source="allocated GCE network")
    if (
        authored.cidr
        and candidate.prefixlen
        != _ipv4_subnet(
            authored.cidr,
            source=_AUTHORED_NETWORK_SOURCE,
        ).prefixlen
    ):
        raise RaesGceAdapterError("allocated GCE network prefix does not match authored intent")
    if any(candidate.overlaps(existing) for existing in seen_cidrs):
        raise RaesGceAdapterError("allocated GCE network projection contains overlapping subnets")
    seen_cidrs.add(candidate)
    gateway = _rebase_address(authored.gateway, authored.cidr, candidate) if authored.gateway else None
    return replace(authored, cidr=str(candidate), gateway=gateway)


def _teardown_projection(networks: tuple[RaesPlanNetwork, ...]) -> tuple[tuple[str, str], ...]:
    """Build names-only, non-provider placeholder CIDRs after pre-allocation failure."""
    if not networks:
        return ()
    authored_prefixes = {
        _ipv4_subnet(network.cidr, source=_AUTHORED_NETWORK_SOURCE).prefixlen for network in networks if network.cidr
    }
    prefix = next(iter(authored_prefixes), _DEFAULT_PREFIX)
    if len(authored_prefixes) > 1:
        raise RaesGceAdapterError("teardown reconstruction requires one network prefix")
    pool = ipaddress.ip_network(_TEARDOWN_ONLY_NETWORK_CIDR).subnets(new_prefix=prefix)
    return tuple((network.address, str(next(pool))) for network in networks)


def _rebase_address(value: str, authored_cidr: str | None, realized: ipaddress.IPv4Network) -> str:
    """Preserve one authored address's host offset in the realized subnet."""
    if not authored_cidr:
        raise RaesGceAdapterError("network-relative address requires an authored network")
    authored = _ipv4_subnet(authored_cidr, source=_AUTHORED_NETWORK_SOURCE)
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise RaesGceAdapterError("network-relative address must be IPv4") from exc
    if not isinstance(address, ipaddress.IPv4Address) or address not in authored:
        raise RaesGceAdapterError("network-relative address must belong to its authored network")
    candidate = ipaddress.IPv4Address(int(realized.network_address) + int(address) - int(authored.network_address))
    if candidate not in realized:
        raise RaesGceAdapterError("network-relative address does not fit the allocated network")
    return str(candidate)


def _occupied_networks(plan: RaesPlan, config: GCERangeCellConfig) -> tuple[ipaddress.IPv4Network, ...]:
    """Handle occupied networks."""
    values = [network.cidr for network in plan.networks if network.cidr]
    values.extend(config.portal_network_cidrs)
    return tuple(_ipv4_subnet(value, source="existing GCE network") for value in values)


def _ipv4_subnet(value: str, *, source: str) -> ipaddress.IPv4Network:
    """Handle ipv4 subnet."""
    try:
        network = ipaddress.ip_network(value)
    except ValueError as exc:
        raise RaesGceAdapterError(f"{source} must be a valid IP network") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise RaesGceAdapterError(f"{source} must be IPv4")
    return network
