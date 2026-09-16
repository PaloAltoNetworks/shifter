"""Strict scalar and network value readers for serialized RAES plans."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from raes_plan_types import RaesPlanError, RaesPlanImage, RaesPlanNetwork

_MIB = 1024 * 1024


def _mapping(value: object) -> Mapping[str, Any]:
    """Read an optional mapping without discarding a malformed present value."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RaesPlanError(f"plan field must be an object, got {type(value).__name__}")
    return value


def _spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec`` mapping, or an empty mapping."""
    return _mapping(payload.get("spec"))


def _node_spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec.node`` mapping, or an empty mapping."""
    return _mapping(_spec(payload).get("node"))


def _infrastructure_spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec.infrastructure`` mapping, or an empty mapping."""
    return _mapping(_spec(payload).get("infrastructure"))


def _resource_name(address: str, payload: Mapping[str, Any]) -> str:
    """Return the authored name, or the complete canonical resource address."""
    for field in ("name", "node_name"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or (value and not value.strip())):
            raise RaesPlanError(f"{field} must be a string")
    name = payload.get("name") or payload.get("node_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return address


def _os_family(payload: Mapping[str, Any]) -> str:
    """Mirror raes_backend_libvirt._os_family: os_family, else spec.node.os."""
    family = payload.get("os_family")
    if family is not None and not isinstance(family, str):
        raise RaesPlanError("os_family must be a string")
    if isinstance(family, str) and family:
        return family
    node_os = _node_spec(payload).get("os")
    if node_os is not None and not isinstance(node_os, str):
        raise RaesPlanError("node os must be a string")
    return node_os if isinstance(node_os, str) else ""


def _os_identity_term(payload: Mapping[str, Any], field: str) -> str | None:
    """Preserve an authored OS identity and reject conflicting repeated terms."""
    outer = payload.get(field)
    inner = _node_spec(payload).get(field)
    # Public compiler defaults encode an unspecified optional OS term as "".
    outer = None if outer == "" else outer
    inner = None if inner == "" else inner
    _validate_optional_identity_term(outer, field)
    _validate_optional_identity_term(inner, field)
    if outer is not None and inner is not None and outer != inner:
        raise RaesPlanError(f"conflicting {field} in node payload")
    return outer if outer is not None else inner


def _validate_optional_identity_term(value: object, field: str) -> None:
    """Handle validate optional identity term."""
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise RaesPlanError(f"{field} must be a non-empty string")


def _node_count(payload: Mapping[str, Any]) -> int:
    """Default an omitted count only; malformed presence is an admission error."""
    raw = payload.get("count", 1)
    # The public 3.5 compiler emits null for an omitted optional count.
    if raw is None:
        return 1
    if type(raw) is not int or raw < 1:
        raise RaesPlanError("node count must be a positive integer")
    return raw


def _memory_mib(payload: Mapping[str, Any]) -> int | None:
    """Authored RAM -> MiB (mirror raes_backend_libvirt._memory_mib); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("ram")
    if raw is not None and (
        isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw) or raw <= 0
    ):
        raise RaesPlanError("ram must be a positive finite number")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        if raw >= _MIB:
            return max(128, int((raw + _MIB - 1) // _MIB))
        return max(128, int(raw))
    return None


def _vcpus(payload: Mapping[str, Any]) -> int | None:
    """Authored CPU -> vcpus (mirror raes_backend_libvirt._vcpus); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("cpu")
    if raw is not None and (
        isinstance(raw, bool)
        or not isinstance(raw, int | float)
        or not math.isfinite(raw)
        or raw <= 0
        or raw != int(raw)
    ):
        raise RaesPlanError("cpu must be a positive whole number")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        return max(1, int(raw))
    return None


def _image(payload: Mapping[str, Any]) -> RaesPlanImage | None:
    """Authored image from spec.node.source (name verbatim, mirror _image_ref)."""
    source = _node_spec(payload).get("source")
    if source is None:
        return None
    if isinstance(source, str) and source.strip():
        return RaesPlanImage(name=source.strip())
    if isinstance(source, Mapping):
        return _mapping_image(source)
    raise RaesPlanError("source must be a named string or mapping")


def _mapping_image(source: Mapping[str, Any]) -> RaesPlanImage:
    """Handle mapping image."""
    name = source.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RaesPlanError("source must be a named string or mapping")
    version = source.get("version")
    if version is not None and (not isinstance(version, str) or (version and not version.strip())):
        raise RaesPlanError("source version must be a string")
    return RaesPlanImage(
        name=name.strip(),
        version=version.strip() if isinstance(version, str) and version.strip() else None,
    )


def _network_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the network handles a node references (``networks`` then ``links``)."""
    infra = _infrastructure_spec(payload)
    for field_name in ("networks", "links"):
        raw = infra.get(field_name)
        if raw is None:
            continue
        if isinstance(raw, list | tuple):
            if any(not isinstance(ref, str) or not ref.strip() for ref in raw):
                raise RaesPlanError("network references must be non-empty strings")
            return tuple(raw)
        raise RaesPlanError("network references must be a list")
    return ()


def _network_selection_open(payload: Mapping[str, Any]) -> bool:
    """Return whether network placement is deliberately left to the backend."""
    infrastructure = _infrastructure_spec(payload)
    return "networks" not in infrastructure and "links" not in infrastructure


def _network(address: str, payload: Mapping[str, Any]) -> RaesPlanNetwork:
    """Build an RaesPlanNetwork from a network resource payload (cidr/gateway/internal)."""
    props = _mapping(_infrastructure_spec(payload).get("properties"))
    cidr = props.get("cidr")
    gateway = props.get("gateway")
    _validate_network_term(cidr, "cidr")
    _validate_network_term(gateway, "gateway")
    if "internal" in props and type(props["internal"]) is not bool:
        raise RaesPlanError("network internal must be a boolean")
    return RaesPlanNetwork(
        address=address,
        name=_resource_name(address, payload),
        cidr=cidr.strip() if isinstance(cidr, str) and cidr.strip() else None,
        gateway=gateway.strip() if isinstance(gateway, str) and gateway.strip() else None,
        internal=props.get("internal") is True,
    )


def _validate_network_term(value: object, field: str) -> None:
    """Handle validate network term."""
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise RaesPlanError(f"network {field} must be a non-empty string")


def _identity_lookup(resources: list[tuple[str, Mapping[str, Any]]], kind: str) -> dict[str, str]:
    """Map every handle a resource may be referenced by to its canonical address.

    Handles are the canonical address, the authored name, and the address leaf.
    Fails closed (ADR-032-R7) when two distinct resources of ``kind`` share a
    handle, since a reference to that handle would be ambiguous.
    """
    lookup: dict[str, str] = {}
    for address, payload in resources:
        name = _resource_name(address, payload)
        for key in (address, name, address.rsplit(".", 1)[-1]):
            if not key:
                continue
            existing = lookup.get(key)
            if existing is not None and existing != address:
                raise RaesPlanError(f"duplicate {kind} alias {key!r} maps to {existing!r} and {address!r}")
            lookup[key] = address
    return lookup
