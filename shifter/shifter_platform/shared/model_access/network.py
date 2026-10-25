"""Exact broker egress and transport-peer binding; no forwarded-header authority."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

from shared.model_access.catalog import ContractError

# RFC 1918 address-space boundaries, not deployment endpoints. S1313 review:
# these protocol constants must remain fixed to reject other special-use space.
RFC1918_IPV4_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),  # NOSONAR(S1313)
    ipaddress.IPv4Network("172.16.0.0/12"),  # NOSONAR(S1313)
    ipaddress.IPv4Network("192.168.0.0/16"),  # NOSONAR(S1313)
)


def private_listener_address(value: str) -> str:
    """Bind only the explicit private pod address supplied by deployment readback."""
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in RFC1918_IPV4_NETWORKS):
        raise ValueError("model listener requires an explicit private IPv4 address")
    return str(address)


def broker_egress_destination(value: object, *, expected_vip: str, egress_mode: str) -> str:
    """Validate the admitted capability against deployment-owned endpoint identity."""
    if not isinstance(value, Mapping) or set(value) != {"contract_version", "vip", "port"}:
        raise ContractError("network.invalid_broker_capability")
    if value["contract_version"] != "model-broker-egress/v1" or type(value["port"]) is not int or value["port"] != 443:
        raise ContractError("network.invalid_broker_capability")
    if egress_mode not in {"status-quo", "deny-all", "allowlist"}:
        raise ContractError("network.incompatible_egress")
    if not isinstance(value["vip"], str) or value["vip"] != expected_vip:
        raise ContractError("network.broker_destination_mismatch")
    try:
        address = ipaddress.IPv4Address(expected_vip)
    except (ValueError, TypeError) as exc:
        raise ContractError("network.invalid_broker_vip") from exc
    if not any(address in network for network in RFC1918_IPV4_NETWORKS):
        raise ContractError("network.invalid_broker_vip")
    return f"{address}/32"


def peer_matches_binding(transport_peer: str, admitted_subnet: str) -> bool:
    """Compare the socket peer with Engine's trusted current subnet binding.

    Callers supply socket transport metadata, never Forwarded/X-Forwarded-For.
    IPv6 and mapped addresses are unsupported on the v1 GCE IPv4 path.
    """
    try:
        peer = ipaddress.IPv4Address(transport_peer)
        network = ipaddress.IPv4Network(admitted_subnet, strict=True)
    except (ValueError, TypeError):
        return False
    return any(network.subnet_of(private) for private in RFC1918_IPV4_NETWORKS) and peer in network
