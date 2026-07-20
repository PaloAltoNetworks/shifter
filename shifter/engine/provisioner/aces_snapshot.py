"""Bounded, redacted runtime-snapshot resources for the ACES provision path (ADR-031-R4).

Reduces a parsed serialized ACES plan to the minimal ``resources`` structure the
``runtime_snapshot`` sidecar record carries. It emits ONLY authored addresses +
resource types + a coarse status -- never the raw GCE apply outputs, which carry
``secret``/``password``/``cidr``/``subnet``/``ami`` keys and values that the
write-boundary validator rejects and the ADR-031-R4 substring contract forbids.
"""

from __future__ import annotations

from aces_plan import AcesPlan

_PROVISIONED = "provisioned"


def snapshot_resources(plan: AcesPlan) -> list[dict[str, str]]:
    """Return bounded ``{address, resource_type, status}`` entries for a plan.

    Represents the provisioned topology (networks + nodes) for the runtime_snapshot
    record. Addresses are authored ACES handles (e.g. ``provision.node.web``) and
    carry no infrastructure detail, so the result is safe for the redacted sidecar.
    """
    resources: list[dict[str, str]] = [
        {"address": network.address, "resource_type": "network", "status": _PROVISIONED} for network in plan.networks
    ]
    resources.extend({"address": node.address, "resource_type": "node", "status": _PROVISIONED} for node in plan.nodes)
    return resources
