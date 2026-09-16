"""Bounded, redacted runtime-snapshot resources for the RAES provision path (ADR-031-R4).

Reduces a parsed serialized RAES plan plus its exact composition proof set to the
minimal ``resources`` structure the ``runtime_snapshot`` sidecar record carries.
It emits ONLY authored addresses + resource types + a coarse status -- never the
raw GCE apply outputs, which carry ``secret``/``password``/``cidr``/``subnet``/
``ami`` keys and values that the write-boundary validator rejects and the
ADR-031-R4 substring contract forbids.
"""

from __future__ import annotations

import json

from raes_plan import RaesPlan

_PROVISIONED = "provisioned"
_MAX_PAYLOAD_BYTES = 65536
_PAYLOAD_METADATA_RESERVE_BYTES = 1024


def _composition_resources(plan: RaesPlan) -> list[tuple[str, str]]:
    """Return authored composition addresses paired with evidence types."""
    return [
        *((item.address, "content-placement") for item in plan.content),
        *((account.address, "account-placement") for account in plan.accounts),
        *((feature.address, "feature-binding") for feature in plan.features),
    ]


def snapshot_resources(
    plan: RaesPlan,
    verified_composition_addresses: set[str] | frozenset[str] | None = None,
) -> list[dict[str, str]]:
    """Return bounded ``{address, resource_type, status}`` entries for a plan.

    Represents provisioned topology plus verified authored composition for the
    runtime_snapshot record. Addresses are compiled RAES handles and carry no
    authored values or infrastructure detail, so the result is safe for the
    redacted sidecar.
    """
    resources: list[dict[str, str]] = [
        {"address": network.address, "resource_type": "network", "status": _PROVISIONED} for network in plan.networks
    ]
    resources.extend({"address": node.address, "resource_type": "node", "status": _PROVISIONED} for node in plan.nodes)
    composition = _composition_resources(plan)
    expected = {address for address, _resource_type in composition}
    verified = set(verified_composition_addresses or ())
    if verified != expected:
        raise ValueError("RAES composition verification coverage is incomplete")
    resources.extend(
        {"address": address, "resource_type": resource_type, "status": "verified"}
        for address, resource_type in composition
    )
    encoded = json.dumps(
        {"operation_id": "0" * 64, "resources": resources},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(encoded) > _MAX_PAYLOAD_BYTES - _PAYLOAD_METADATA_RESERVE_BYTES:
        raise ValueError("RAES runtime snapshot exceeds the persistence size bound")
    return resources
