"""Cleanup of only the GCE resources created during a failed RAES apply attempt."""

from __future__ import annotations

import logging

from gcp_range_cell_ops import _delete_resource, _get_or_none
from gcp_range_cell_types import RangeCellPlan
from gcp_range_cells import _ensure_attached_disks_auto_delete
from raes_account_credentials import delete_instance_account_credentials
from raes_gcp_apply_types import RaesGceApplyRuntime
from raes_gcp_destroy import _instance_accounts
from raes_plan import RaesPlan

logger = logging.getLogger(__name__)


def _cleanup_created_resources(
    plan: RangeCellPlan,
    raes_plan: RaesPlan,
    runtime: RaesGceApplyRuntime,
    created: list[tuple[str, str]],
) -> None:
    """Release only this attempt's resources after a late foreign-VM conflict."""
    clients = runtime.clients
    services = {
        "instance": (clients.instances, "zone", "instance", {"zone": plan["zone"]}),
        "address": (clients.addresses, "region", "address", {"region": plan["region"]}),
        "firewall": (clients.firewalls, "global", "firewall", {}),
        "router": (clients.routers, "region", "router", {"region": plan["region"]}),
        "subnetwork": (clients.subnetworks, "region", "subnetwork", {"region": plan["region"]}),
        "network": (clients.networks, "global", "network", {}),
    }
    instances = {instance["resource_name"]: instance for instance in plan["instances"]}
    for kind, name in reversed(created):
        service, scope, field, extra = services[kind]
        try:
            if kind == "instance":
                existing = _get_or_none(
                    clients.instances.get,
                    clients.google_exceptions,
                    project=plan["project_id"],
                    zone=plan["zone"],
                    instance=name,
                )
                if existing is not None:
                    _ensure_attached_disks_auto_delete(plan, clients, name, existing)
            _delete_resource(
                plan,
                clients,
                service.get,
                service.delete,
                scope,
                project=plan["project_id"],
                **extra,
                **{field: name},
            )
            if kind == "instance":
                instance = instances[name]
                runtime.secret_ops.delete_ssh(plan["range_id"], instance["uuid"])
                delete_instance_account_credentials(
                    plan["range_id"],
                    instance["uuid"],
                    _instance_accounts(raes_plan, instance),
                    runtime.account_secret_ops,
                )
        except Exception:
            logger.exception("Failed to clean attempt-created GCE resource kind=%s", kind)
