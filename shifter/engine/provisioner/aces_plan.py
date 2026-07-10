"""Provisioner-side reader for the serialized ACES ProvisioningPlan (ADR-031, ADR-032).

The ACES-native provisioning path persists the *serialized ACES ProvisioningPlan*
in ``mission_control_range.range_config`` (see
``shifter_platform/shared/aces/runtime_target.py::serialize_provisioning_plan``).
The provisioner is a separate deployable whose image ships only ``cyberscript`` on
``PYTHONPATH`` (no ``shared``, no Pydantic) and must not import any ``aces_*`` SDL
package (ADR-024). So it reads the plan as plain data here.

Per ADR-032, Shifter does not re-model the plan into a Shifter-owned spec: this
module reads the ACES plan payloads via accessors that **mirror the reference
ACES backend** ``aces_backend_libvirt`` (``_payload.py`` / ``realization.py``) --
``os_family`` from ``payload.os_family`` then ``spec.node.os``; the image from
``spec.node.source`` (name verbatim); sizing from ``spec.node.resources.ram``
(bytes -> MiB) and ``.cpu``; network membership from ``spec.infrastructure``. A
platform-side drift test compares this module's extraction against the reference
backend so the two cannot diverge.

Sizing/image are exposed as ``None`` when the author omitted them, so the backend
applies its own default (e.g. a GCE profile machine type) rather than a forced
constant. It self-discriminates on the plan ``kind`` so an ``aces-range`` command
run against a cyberscript ``range_config`` fails loudly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Must equal ``shared.aces.runtime_target.ACES_PROVISIONING_PLAN_KIND``.
ACES_PROVISIONING_PLAN_KIND = "aces_provisioning_plan"
NODE_RESOURCE_TYPE = "node"
NETWORK_RESOURCE_TYPE = "network"

_MIB = 1024 * 1024


class AcesPlanError(ValueError):
    """Raised when a persisted range_config is not a well-formed serialized ACES plan."""


@dataclass(frozen=True)
class AcesPlanImage:
    """Authored image reference (from ACES ``source``); resolved to a concrete
    provider image by the backend at realization (ADR-032-R2)."""

    name: str
    version: str | None = None


@dataclass(frozen=True)
class AcesPlanNode:
    """A compute node to provision, with authored intent extracted verbatim."""

    address: str
    name: str
    os_family: str
    count: int
    network_addresses: tuple[str, ...]
    ram_mib: int | None = None
    vcpus: int | None = None
    image: AcesPlanImage | None = None


@dataclass(frozen=True)
class AcesPlanNetwork:
    """A network the range's nodes attach to."""

    address: str
    name: str
    cidr: str | None = None
    gateway: str | None = None
    internal: bool = False


@dataclass(frozen=True)
class AcesPlan:
    """The parsed serialized ACES plan: nodes + networks for realization."""

    aces_sdl_version: str
    nodes: tuple[AcesPlanNode, ...]
    networks: tuple[AcesPlanNetwork, ...]


def _mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


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
    """Return the authored resource name, falling back to the address leaf."""
    name = payload.get("name") or payload.get("node_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return address.rsplit(".", 1)[-1]


def _os_family(payload: Mapping[str, Any]) -> str:
    """Mirror aces_backend_libvirt._os_family: os_family, else spec.node.os."""
    family = payload.get("os_family")
    if isinstance(family, str) and family:
        return family
    node_os = _node_spec(payload).get("os")
    return node_os if isinstance(node_os, str) else ""


def _node_count(payload: Mapping[str, Any]) -> int:
    """Return the node instance count (>= 1); default 1 for missing/invalid values."""
    raw = payload.get("count")
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int) and raw >= 1:
        return raw
    return 1


def _memory_mib(payload: Mapping[str, Any]) -> int | None:
    """Authored RAM -> MiB (mirror aces_backend_libvirt._memory_mib); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("ram")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        if raw >= _MIB:
            return max(128, int((raw + _MIB - 1) // _MIB))
        return max(128, int(raw))
    return None


def _vcpus(payload: Mapping[str, Any]) -> int | None:
    """Authored CPU -> vcpus (mirror aces_backend_libvirt._vcpus); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("cpu")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        return max(1, int(raw))
    return None


def _image(payload: Mapping[str, Any]) -> AcesPlanImage | None:
    """Authored image from spec.node.source (name verbatim, mirror _image_ref)."""
    source = _node_spec(payload).get("source")
    if isinstance(source, str) and source.strip():
        return AcesPlanImage(name=source.strip())
    if isinstance(source, Mapping):
        name = source.get("name")
        if isinstance(name, str) and name.strip():
            version = source.get("version")
            return AcesPlanImage(
                name=name.strip(),
                version=version.strip() if isinstance(version, str) and version.strip() else None,
            )
    return None


def _network_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the network handles a node references (``networks`` then ``links``)."""
    infra = _infrastructure_spec(payload)
    for field_name in ("networks", "links"):
        raw = infra.get(field_name)
        if isinstance(raw, list | tuple):
            return tuple(ref for ref in raw if isinstance(ref, str) and ref.strip())
    return ()


def _network(address: str, payload: Mapping[str, Any]) -> AcesPlanNetwork:
    """Build an AcesPlanNetwork from a network resource payload (cidr/gateway/internal)."""
    props = _mapping(_infrastructure_spec(payload).get("properties"))
    cidr = props.get("cidr")
    gateway = props.get("gateway")
    return AcesPlanNetwork(
        address=address,
        name=_resource_name(address, payload),
        cidr=cidr.strip() if isinstance(cidr, str) and cidr.strip() else None,
        gateway=gateway.strip() if isinstance(gateway, str) and gateway.strip() else None,
        internal=props.get("internal") is True,
    )


def _network_lookup(networks: list[tuple[str, Mapping[str, Any]]]) -> dict[str, str]:
    """Map every handle a node might reference a network by to its canonical address."""
    lookup: dict[str, str] = {}
    for address, payload in networks:
        name = _resource_name(address, payload)
        for key in (address, name, address.rsplit(".", 1)[-1]):
            if key:
                lookup[key] = address
    return lookup


def parse_plan(range_config: dict[str, Any] | None) -> AcesPlan:
    """Parse a serialized ACES plan from a range_config dict.

    Self-discriminates on ``kind`` so an ``aces-range`` command run against a
    cyberscript (or otherwise foreign) ``range_config`` raises rather than
    realizing an unintended topology.
    """
    envelope = _require_mapping(range_config, where="range_config")
    kind = envelope.get("kind")
    if kind != ACES_PROVISIONING_PLAN_KIND:
        raise AcesPlanError(f"kind must be {ACES_PROVISIONING_PLAN_KIND!r}, got {kind!r}")

    resources = _require_mapping(envelope.get("resources"), where="resources")
    network_pairs: list[tuple[str, Mapping[str, Any]]] = []
    node_pairs: list[tuple[str, Mapping[str, Any]]] = []
    for entry in resources.values():
        entry_map = _require_mapping(entry, where="resource")
        address = _string(entry_map.get("address"), where="resource.address")
        payload = _require_mapping(entry_map.get("payload"), where="resource.payload")
        resource_type = entry_map.get("resource_type")
        if resource_type == NETWORK_RESOURCE_TYPE:
            network_pairs.append((address, payload))
        elif resource_type == NODE_RESOURCE_TYPE:
            node_pairs.append((address, payload))

    lookup = _network_lookup(network_pairs)
    networks = tuple(_network(address, payload) for address, payload in sorted(network_pairs))
    nodes = tuple(_node(address, payload, lookup) for address, payload in sorted(node_pairs))

    version = envelope.get("aces_sdl_version")
    return AcesPlan(
        aces_sdl_version=version if isinstance(version, str) else "",
        nodes=nodes,
        networks=networks,
    )


def _node(address: str, payload: Mapping[str, Any], lookup: dict[str, str]) -> AcesPlanNode:
    """Build an AcesPlanNode, extracting authored intent and resolving network refs."""
    resolved = tuple(dict.fromkeys(lookup[ref] for ref in _network_refs(payload) if ref in lookup))
    return AcesPlanNode(
        address=address,
        name=_resource_name(address, payload),
        os_family=_os_family(payload),
        count=_node_count(payload),
        network_addresses=resolved,
        ram_mib=_memory_mib(payload),
        vcpus=_vcpus(payload),
        image=_image(payload),
    )


def _require_mapping(value: object, *, where: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping or raise AcesPlanError naming ``where``."""
    if not isinstance(value, Mapping):
        raise AcesPlanError(f"{where} must be an object, got {type(value).__name__}")
    return value


def _string(value: object, *, where: str) -> str:
    """Return ``value`` as a non-empty string or raise AcesPlanError naming ``where``."""
    if not isinstance(value, str) or not value.strip():
        raise AcesPlanError(f"{where} must be a non-empty string")
    return value
