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

from config import load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_model_broker import broker_firewall_name
from gcp_range_cell_ops import _get_or_none
from gcp_range_cell_types import RangeCellPlan
from raes_gcp_destroy import RaesGceDestroyOptions, _default_destroy_profile
from raes_gcp_plan import RaesGcePlanOptions, build_raes_range_cell_plan
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


def _reconstructed_plan(
    request_uuid: str, range_id: int, raes_plan: RaesPlan, options: RaesGceDestroyOptions
) -> RangeCellPlan:
    """Rebuild the plan exactly as destroy rebuilt it: resource names only."""
    return build_raes_range_cell_plan(
        request_uuid,
        range_id,
        raes_plan,
        _default_destroy_profile,
        RaesGcePlanOptions(
            config=options.config or load_gce_range_cell_config(),
            allocated_network_cidrs=options.allocated_network_cidrs,
            reconstruct_for_teardown=options.reconstruct_without_allocation,
            remote_access=options.remote_access,
        ),
    )


def _owned_compute(plan: RangeCellPlan) -> list[tuple[str, str]]:
    """Return every owned ``(instance, address)`` pair."""
    return [(instance["resource_name"], instance["address_name"]) for instance in plan["instances"]]


def _check_compute(tally: _Tally, clients: GCEClients, plan: RangeCellPlan) -> None:
    """Read back every owned instance and its address."""
    for instance_name, address_name in _owned_compute(plan):
        tally.check(
            clients,
            "instances",
            clients.instances.get,
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance_name,
        )
        tally.check(
            clients,
            "addresses",
            clients.addresses.get,
            project=plan["project_id"],
            region=plan["region"],
            address=address_name,
        )


def _check_network(tally: _Tally, clients: GCEClients, plan: RangeCellPlan, range_id: int) -> None:
    """Read back the owned router, firewalls, subnets, and an owned network."""
    project = plan["project_id"]
    router_nat = plan.get("router_nat")
    if router_nat is not None:
        tally.check(
            clients,
            "routers",
            clients.routers.get,
            project=project,
            region=plan["region"],
            router=router_nat["router_name"],
        )
    firewall_names = {rule["name"] for rule in plan["firewalls"]} | {broker_firewall_name(range_id)}
    for firewall_name in sorted(firewall_names):
        tally.check(clients, "firewalls", clients.firewalls.get, project=project, firewall=firewall_name)
    for subnet in plan["subnets"]:
        tally.check(
            clients,
            "subnets",
            clients.subnetworks.get,
            project=project,
            region=plan["region"],
            subnetwork=subnet["resource_name"],
        )
    if plan["manage_network"]:
        tally.check(clients, "networks", clients.networks.get, project=project, network=plan["network"]["name"])


def _outcome(tally: _Tally) -> str:
    """Return the closed inventory outcome: unknown wins over residuals over absence."""
    if tally.incomplete:
        return INCOMPLETE
    if tally.residuals:
        return RESIDUALS_FOUND
    return VERIFIED_ABSENT


def inventory_raes_range_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    options: RaesGceDestroyOptions | None = None,
) -> dict[str, Any]:
    """Inventory the RAES range cell's owned resources after teardown.

    Returns a dict ``{outcome, residual_categories, scope}`` suitable for the
    terminal destroy result payload. ``options`` are the destroy's own options:
    the plan is rebuilt exactly as destroy rebuilt it (names only), then each owned
    resource is read back. No observation timestamp is carried in the payload --
    it would make the digested terminal result differ on redelivery; the Engine
    applier stamps the observation time from the result row.
    """
    resolved_options = options or RaesGceDestroyOptions()
    resolved_clients = resolved_options.clients or _build_clients()
    plan = _reconstructed_plan(request_uuid, range_id, raes_plan, resolved_options)

    tally = _Tally()
    project = plan["project_id"]
    _check_compute(tally, resolved_clients, plan)
    _check_network(tally, resolved_clients, plan, range_id)
    outcome = _outcome(tally)
    return {
        "outcome": outcome,
        "residual_categories": [{"category": name, "count": count} for name, count in sorted(tally.residuals.items())],
        "scope": {"project": project, "region": plan["region"], "zone": plan["zone"], "categories": list(_CATEGORIES)},
    }
