"""Serialized resource collection for the provisioner ACES plan reader."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aces_plan_domain import topology, topology_signature, topology_text
from aces_plan_types import AcesPlanError

NODE_RESOURCE_TYPE = "node"
NETWORK_RESOURCE_TYPE = "network"
CONTENT_RESOURCE_TYPE = "content-placement"
FEATURE_RESOURCE_TYPE = "feature-binding"
ACCOUNT_RESOURCE_TYPE = "account-placement"

SUPPORTED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {NODE_RESOURCE_TYPE, NETWORK_RESOURCE_TYPE, CONTENT_RESOURCE_TYPE, FEATURE_RESOURCE_TYPE, ACCOUNT_RESOURCE_TYPE}
)


@dataclass
class ResourceCollection:
    """Mutable buckets assembled while validating serialized plan resources."""

    network_pairs: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)
    node_pairs: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)
    composition: dict[str, list[tuple[str, Mapping[str, Any]]]] = field(
        default_factory=lambda: {
            CONTENT_RESOURCE_TYPE: [],
            FEATURE_RESOURCE_TYPE: [],
            ACCOUNT_RESOURCE_TYPE: [],
        }
    )
    seen_addresses: set[str] = field(default_factory=set)
    ordering_dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    topology_signatures: dict[str, tuple[object, ...]] = field(default_factory=dict)


def _require_mapping(value: object, *, where: str) -> Mapping[str, Any]:
    """Return a mapping or raise a bounded plan error naming its location."""
    if not isinstance(value, Mapping):
        raise AcesPlanError(f"{where} must be an object, got {type(value).__name__}")
    return value


def _string(value: object, *, where: str) -> str:
    """Return a non-empty string or raise a bounded plan error."""
    if not isinstance(value, str) or not value.strip():
        raise AcesPlanError(f"{where} must be a non-empty string")
    return value


def _dependencies(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Return unique ordering dependencies from one serialized resource."""
    raw = entry.get("ordering_dependencies")
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple) or any(not isinstance(item, str) or not item for item in raw):
        raise AcesPlanError("resource ordering_dependencies must be a list of non-empty strings")
    return tuple(dict.fromkeys(raw))


def _record_topology(collection: ResourceCollection, payload: Mapping[str, Any]) -> None:
    """Record and compare the domain identity carried by one resource."""
    value = topology(payload)
    if not value:
        return
    domain_id = topology_text(value, "domain_id")
    signature = topology_signature(value)
    previous = collection.topology_signatures.get(domain_id)
    if previous is not None and previous != signature:
        raise AcesPlanError("domain topology identity is inconsistent")
    collection.topology_signatures[domain_id] = signature


def _record_resource(
    collection: ResourceCollection,
    resource_type: str,
    address: str,
    payload: Mapping[str, Any],
) -> None:
    """Place one validated resource in its process-local parsing bucket."""
    pair = (address, payload)
    if resource_type == NETWORK_RESOURCE_TYPE:
        collection.network_pairs.append(pair)
    elif resource_type == NODE_RESOURCE_TYPE:
        collection.node_pairs.append(pair)
    else:
        collection.composition[resource_type].append(pair)


def _collect_resource(collection: ResourceCollection, entry: object) -> None:
    """Validate and collect one serialized plan resource."""
    entry_map = _require_mapping(entry, where="resource")
    address = _string(entry_map.get("address"), where="resource.address")
    if address in collection.seen_addresses:
        raise AcesPlanError(f"duplicate resource address {address!r}")
    collection.seen_addresses.add(address)
    payload = _require_mapping(entry_map.get("payload"), where="resource.payload")
    collection.ordering_dependencies[address] = _dependencies(entry_map)
    _record_topology(collection, payload)
    resource_type = entry_map.get("resource_type")
    if not isinstance(resource_type, str) or resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise AcesPlanError(
            f"unsupported resource_type {resource_type!r} at {address} (supported: {sorted(SUPPORTED_RESOURCE_TYPES)})"
        )
    _record_resource(collection, resource_type, address, payload)


def collect_resources(resources: Mapping[str, Any]) -> ResourceCollection:
    """Validate all serialized resources and return categorized buckets."""
    collection = ResourceCollection()
    for entry in resources.values():
        _collect_resource(collection, entry)
    return collection
