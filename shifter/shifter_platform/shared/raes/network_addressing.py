"""Fail-closed admission for RAES 3.5 static network addresses (#2219)."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping

from raes_contracts.diagnostics import Diagnostic
from raes_contracts.planning import PlannedResource

INVALID_STATIC_NETWORK_ADDRESS_CODE = "shifter-provisioner.invalid-static-network-address"
_Claim = tuple[str, ipaddress.IPv4Address]


class _InvalidStaticAddress(ValueError):
    """A bounded producer-side static-address validation failure."""


def _infrastructure(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return one resource's infrastructure mapping, or an empty mapping."""
    spec = payload.get("spec")
    infrastructure = spec.get("infrastructure") if isinstance(spec, Mapping) else None
    return infrastructure if isinstance(infrastructure, Mapping) else {}


def _network_handles(
    resources: list[tuple[PlannedResource, Mapping[str, object]]],
) -> tuple[dict[str, str], dict[str, ipaddress.IPv4Network | None]]:
    """Build canonical network aliases and their authored IPv4 subnets."""
    lookup: dict[str, str] = {}
    networks: dict[str, ipaddress.IPv4Network | None] = {}
    for resource, payload in resources:
        for handle in _resource_handles(resource, payload):
            lookup[handle] = resource.address
        networks[resource.address] = _network_cidr(payload)
    return lookup, networks


def _resource_handles(resource: PlannedResource, payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return the stable aliases accepted for one planned network."""
    name = payload.get("name") or payload.get("node_name")
    candidates = (resource.address, name, resource.address.rsplit(".", 1)[-1])
    return tuple(handle for handle in candidates if isinstance(handle, str) and handle)


def _network_cidr(payload: Mapping[str, object]) -> ipaddress.IPv4Network | None:
    """Parse one canonical authored IPv4 subnet, returning None on invalid intent."""
    properties = _infrastructure(payload).get("properties")
    cidr = properties.get("cidr") if isinstance(properties, Mapping) else None
    if not isinstance(cidr, str):
        return None
    try:
        parsed = ipaddress.ip_network(cidr, strict=True)
    except ValueError:
        return None
    return parsed if isinstance(parsed, ipaddress.IPv4Network) else None


def _node_networks(payload: Mapping[str, object], lookup: Mapping[str, str]) -> tuple[str, ...]:
    """Resolve the node's authored network list through canonical aliases."""
    infrastructure = _infrastructure(payload)
    raw = infrastructure.get("networks")
    if raw is None:
        raw = infrastructure.get("links")
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(lookup[ref] for ref in raw if isinstance(ref, str) and ref in lookup)


def static_network_address_diagnostics(
    node_resources: list[tuple[PlannedResource, Mapping[str, object]]],
    network_resources: list[tuple[PlannedResource, Mapping[str, object]]],
    diagnostic_factory: Callable[[str, str, str], Diagnostic],
) -> list[Diagnostic]:
    """Validate static address shape and ownership before plan dispatch."""
    lookup, networks = _network_handles(network_resources)
    diagnostics: list[Diagnostic] = []
    claimed: set[_Claim] = set()
    for resource, payload in node_resources:
        diagnostics.extend(
            _node_static_address_diagnostics(resource, payload, lookup, networks, claimed, diagnostic_factory)
        )
    return diagnostics


def _node_static_address_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    lookup: Mapping[str, str],
    networks: Mapping[str, ipaddress.IPv4Network | None],
    claimed: set[_Claim],
    diagnostic_factory: Callable[[str, str, str], Diagnostic],
) -> list[Diagnostic]:
    """Validate and reserve every static-address claim for one node."""
    properties = _infrastructure(payload).get("properties")
    if properties in (None, []):
        return []
    invalid_message = None
    if not isinstance(properties, list | tuple):
        invalid_message = "static network properties must be a list of one-network address entries"
    elif payload.get("count", 1) != 1:
        invalid_message = "static network addressing requires exactly one node instance"
    if invalid_message is not None:
        return [
            _diagnostic(
                resource,
                invalid_message,
                diagnostic_factory,
            )
        ]
    assert isinstance(properties, list | tuple)

    attached = _node_networks(payload, lookup)
    primary = attached[0] if attached else None
    node_networks: set[str] = set()
    diagnostics: list[Diagnostic] = []
    for entry in properties:
        try:
            claim = _validated_claim(entry, primary, lookup, networks, node_networks, claimed)
        except _InvalidStaticAddress as exc:
            diagnostics.append(_diagnostic(resource, str(exc), diagnostic_factory))
            continue
        claimed.add(claim)
        node_networks.add(claim[0])
    return diagnostics


def _validated_claim(
    entry: object,
    primary: str | None,
    lookup: Mapping[str, str],
    networks: Mapping[str, ipaddress.IPv4Network | None],
    node_networks: set[str],
    claimed: set[_Claim],
) -> _Claim:
    """Return one unique, primary-network, provider-assignable IPv4 claim."""
    if not isinstance(entry, Mapping) or len(entry) != 1:
        raise _InvalidStaticAddress("each static network property must name exactly one network and IPv4 address")
    ref, raw_address = next(iter(entry.items()))
    network_address = lookup.get(ref) if isinstance(ref, str) else None
    if network_address is None or network_address != primary or network_address in node_networks:
        raise _InvalidStaticAddress("static network address must uniquely target the node's primary network")
    address = _assignable_address(raw_address, networks.get(network_address))
    claim = (network_address, address)
    if claim in claimed:
        raise _InvalidStaticAddress("static network address is already claimed by another node")
    return claim


def _assignable_address(raw_address: object, network: ipaddress.IPv4Network | None) -> ipaddress.IPv4Address:
    """Return a valid provider-assignable IPv4 host on the authored network."""
    try:
        address = ipaddress.ip_address(raw_address) if isinstance(raw_address, str) else None
    except ValueError:
        address = None
    if not isinstance(address, ipaddress.IPv4Address) or network is None or address not in network:
        raise _InvalidStaticAddress("static network address must be an assignable IPv4 host on its authored network")
    offset = int(address) - int(network.network_address)
    if offset < 3 or offset > network.num_addresses - 4:
        raise _InvalidStaticAddress("static network address is reserved or unavailable on the target provider")
    return address


def _diagnostic(
    resource: PlannedResource,
    message: str,
    diagnostic_factory: Callable[[str, str, str], Diagnostic],
) -> Diagnostic:
    """Build one bounded admission diagnostic without echoing address values."""
    return diagnostic_factory(INVALID_STATIC_NETWORK_ADDRESS_CODE, resource.address, message)
