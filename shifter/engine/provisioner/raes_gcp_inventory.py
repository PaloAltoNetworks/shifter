"""Post-teardown provider inventory/readback of RAES range-cell resources.

#2086, ADR-063-R4/R5. Verified terminal cleanup requires an independent
inventory/readback, not a logical status. After destroy, this re-checks every
resource the plan owns via a GET on the exact same enumeration ``raes_gcp_destroy``
deletes: NotFound means gone, a returned resource is a residual, and a
non-NotFound provider error makes the inventory ``INCOMPLETE`` (unknown, never an
empty success). The result is emitted with the terminal destroy result so the
Engine applier records durable, scoped inventory/readback evidence before any
consumer reports verified cleanup, prunes retry evidence, or releases capacity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config import GCERangeCellConfig, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_ops import _get_or_none
from raes_gcp_destroy import _default_destroy_profile
from raes_gcp_plan import build_raes_range_cell_plan
from raes_plan import RaesPlan

__all__ = ["INCOMPLETE", "RESIDUALS_FOUND", "VERIFIED_ABSENT", "inventory_raes_range_cell"]

VERIFIED_ABSENT = "VERIFIED_ABSENT"
RESIDUALS_FOUND = "RESIDUALS_FOUND"
INCOMPLETE = "INCOMPLETE"

_CATEGORIES = ("instances", "addresses", "routers", "firewalls", "subnets", "networks")


@dataclass
class _Tally:
    """Running count of residual resources found and whether the inventory completed."""

    residuals: dict[str, int] = field(default_factory=dict)
    incomplete: bool = False

    def check(self, clients: GCEClients, category: str, getter: Callable[..., object], **kwargs: object) -> None:
        """Record a residual when the resource still exists; mark incomplete on a provider error."""
        try:
            if _get_or_none(getter, clients.google_exceptions, **kwargs) is not None:
                self.residuals[category] = self.residuals.get(category, 0) + 1
        except Exception:
            self.incomplete = True


def inventory_raes_range_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    config: GCERangeCellConfig | None = None,
    clients: GCEClients | None = None,
) -> dict[str, Any]:
    """Inventory the RAES range cell's owned resources after teardown.

    Returns a dict ``{outcome, residual_categories, scope}`` suitable for the
    terminal destroy result payload. Rebuilds the plan the same way destroy does
    (names only), then GETs each owned resource. No observation timestamp is
    carried in the payload -- it would make the digested terminal result differ on
    redelivery; the Engine applier stamps the observation time from the result row.
    """
    resolved_config = config or load_gce_range_cell_config()
    resolved_clients = clients or _build_clients()
    plan = build_raes_range_cell_plan(request_uuid, range_id, raes_plan, _default_destroy_profile, resolved_config)

    tally = _Tally()
    project = plan["project_id"]
    for instance in plan["instances"]:
        tally.check(
            resolved_clients,
            "instances",
            resolved_clients.instances.get,
            project=project,
            zone=plan["zone"],
            instance=instance["resource_name"],
        )
        tally.check(
            resolved_clients,
            "addresses",
            resolved_clients.addresses.get,
            project=project,
            region=plan["region"],
            address=instance["address_name"],
        )
    router_nat = plan.get("router_nat")
    if router_nat is not None:
        tally.check(
            resolved_clients,
            "routers",
            resolved_clients.routers.get,
            project=project,
            region=plan["region"],
            router=router_nat["router_name"],
        )
    for firewall in plan["firewalls"]:
        tally.check(
            resolved_clients, "firewalls", resolved_clients.firewalls.get, project=project, firewall=firewall["name"]
        )
    for subnet in plan["subnets"]:
        tally.check(
            resolved_clients,
            "subnets",
            resolved_clients.subnetworks.get,
            project=project,
            region=plan["region"],
            subnetwork=subnet["resource_name"],
        )
    if plan["manage_network"]:
        tally.check(
            resolved_clients,
            "networks",
            resolved_clients.networks.get,
            project=project,
            network=plan["network"]["name"],
        )

    if tally.incomplete:
        outcome = INCOMPLETE
    elif tally.residuals:
        outcome = RESIDUALS_FOUND
    else:
        outcome = VERIFIED_ABSENT
    return {
        "outcome": outcome,
        "residual_categories": [{"category": name, "count": count} for name, count in sorted(tally.residuals.items())],
        "scope": {"project": project, "region": plan["region"], "zone": plan["zone"], "categories": list(_CATEGORIES)},
    }
