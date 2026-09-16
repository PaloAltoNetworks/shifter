"""Adapt portable RAES realization intent to the GCE range-cell core.

The RAE runtime owns the authoritative provisioning plan.  This module makes
only provider choices that the plan explicitly leaves open, producing a copied
backend plan for the GCE core while leaving the portable plan untouched for
completion accounting and runtime feedback.
"""

from __future__ import annotations

import ipaddress
from dataclasses import replace

from config import GCERangeCellConfig
from raes_plan import RaesPlan, RaesPlanNetwork

_DEFAULT_NETWORK_ADDRESS = "backend.gce.network.default"
_DEFAULT_NETWORK_NAME = "backend-default"
_PRIVATE_POOL = ipaddress.IPv4Network("172.16.0.0/12")  # NOSONAR -- RFC 1918 allocation pool.
_DEFAULT_PREFIX = 28
_TEARDOWN_ONLY_NETWORK_CIDR = "198.18.0.0/16"  # NOSONAR -- RFC 2544 teardown placeholder.


class RaesGceAdapterError(ValueError):
    """Raised when open portable intent cannot be safely bound for GCE."""


def adapt_raes_plan_for_gce(
    plan: RaesPlan,
    config: GCERangeCellConfig,
    *,
    allocated_network_cidr: str | None = None,
    reconstruct_for_teardown: bool = False,
) -> RaesPlan:
    """Return the GCE-core plan selected under the runtime's portable plan.

    Nodes with authored network references are preserved byte for byte.  Nodes
    whose compiled infrastructure omits network selection share one internal
    backend subnet.  Shared-VPC mode requires a CIDR from the tenant allocator;
    a per-range VPC can select a non-overlapping private subnet locally.
    """
    open_nodes = tuple(node for node in plan.nodes if node.network_selection_open)
    if not open_nodes:
        return plan
    if any(network.address == _DEFAULT_NETWORK_ADDRESS for network in plan.networks):
        raise RaesGceAdapterError("portable plan collides with the reserved GCE adapter network identity")

    cidr = _default_network_cidr(
        plan,
        config,
        allocated_network_cidr,
        reconstruct_for_teardown=reconstruct_for_teardown,
    )
    network = RaesPlanNetwork(
        address=_DEFAULT_NETWORK_ADDRESS,
        name=_DEFAULT_NETWORK_NAME,
        cidr=cidr,
        internal=True,
    )
    open_addresses = {node.address for node in open_nodes}
    nodes = tuple(
        replace(node, network_addresses=(_DEFAULT_NETWORK_ADDRESS,)) if node.address in open_addresses else node
        for node in plan.nodes
    )
    return replace(plan, nodes=nodes, networks=(*plan.networks, network))


def requires_allocated_gce_network(plan: RaesPlan, config: GCERangeCellConfig) -> bool:
    """Return whether this open plan needs the tenant shared-VPC allocator."""
    return config.network_mode == "shared-vpc" and any(node.network_selection_open for node in plan.nodes)


def _default_network_cidr(
    plan: RaesPlan,
    config: GCERangeCellConfig,
    allocated_network_cidr: str | None,
    *,
    reconstruct_for_teardown: bool,
) -> str:
    """Handle default network cidr."""
    if allocated_network_cidr is not None:
        candidate = _ipv4_subnet(allocated_network_cidr, source="allocated GCE network")
        _require_non_overlapping(candidate, plan, config)
        return str(candidate)
    if config.network_mode == "shared-vpc":
        # A reservation failure happens before apply, but destroy still has to
        # reconstruct deterministic instance/subnet/firewall names and converge.
        # No provider create/update consumes this documentation-only CIDR: the
        # flag is exposed only by the destructive plan path.
        if reconstruct_for_teardown:
            return _TEARDOWN_ONLY_NETWORK_CIDR
        raise RaesGceAdapterError("open network selection requires a tenant-allocated shared-VPC subnet")

    occupied = _occupied_networks(plan, config)
    for candidate in _PRIVATE_POOL.subnets(new_prefix=_DEFAULT_PREFIX):
        if not any(candidate.overlaps(other) for other in occupied):
            return str(candidate)
    raise RaesGceAdapterError("no private GCE subnet is available for open network selection")


def _require_non_overlapping(
    candidate: ipaddress.IPv4Network,
    plan: RaesPlan,
    config: GCERangeCellConfig,
) -> None:
    """Handle require non overlapping."""
    if any(candidate.overlaps(other) for other in _occupied_networks(plan, config)):
        raise RaesGceAdapterError("allocated GCE adapter subnet overlaps an existing range or portal network")


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
