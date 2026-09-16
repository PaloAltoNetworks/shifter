"""Teardown of every GCE resource owned by one range cell."""

from __future__ import annotations

import logging

from config import GCERangeCellConfig, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_credentials import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _default_secret_ops,
    _default_vertex_ops,
)
from gcp_range_cell_ops import _delete_resource, _get_or_none, _wait_for_operation
from gcp_range_cell_plan import render_range_cell_plan
from gcp_range_cell_types import RangeCellPlan, ResourceDict
from provisioner_db import get_range_data_by_request_id
from range_placement import resolve_placement_from_range_data

logger = logging.getLogger(__name__)


def _destroy_vpn_gateway(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Delete the request-owned OpenVPN gateway instance and its address."""
    gateway = plan.get("vpn_gateway")
    if gateway is None:
        return
    _delete_resource(
        plan,
        clients,
        clients.instances.get,
        clients.instances.delete,
        "zone",
        project=plan["project_id"],
        zone=plan["zone"],
        instance=gateway["resource_name"],
    )
    _delete_resource(
        plan,
        clients,
        clients.addresses.get,
        clients.addresses.delete,
        "region",
        project=plan["project_id"],
        region=plan["region"],
        address=gateway["address_name"],
    )


def _mark_disks_auto_delete(plan: RangeCellPlan, clients: GCEClients, resource_name: str) -> None:
    """Flag every retained disk of an existing instance so its delete reclaims them."""
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=resource_name,
    )
    if existing is None:
        return
    for disk in getattr(existing, "disks", None) or []:
        if bool(getattr(disk, "auto_delete", False)):
            continue
        device_name = str(getattr(disk, "device_name", "") or "")
        if not device_name:
            raise RuntimeError("GCE range instance has an attached disk without a device name")
        operation = clients.instances.set_disk_auto_delete(
            project=plan["project_id"],
            zone=plan["zone"],
            instance=resource_name,
            device_name=device_name,
            auto_delete=True,
        )
        _wait_for_operation(plan, clients, operation, "zone")


def _destroy_instances(plan: RangeCellPlan, clients: GCEClients, secret_ops: GCEGuestSecretOps) -> None:
    """Delete range instances, their addresses, and their guest secrets."""
    for instance in reversed(plan["instances"]):
        _mark_disks_auto_delete(plan, clients, instance["resource_name"])
        _delete_resource(
            plan,
            clients,
            clients.instances.get,
            clients.instances.delete,
            "zone",
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance["resource_name"],
        )
        _delete_resource(
            plan,
            clients,
            clients.addresses.get,
            clients.addresses.delete,
            "region",
            project=plan["project_id"],
            region=plan["region"],
            address=instance["address_name"],
        )
        secret_ops.delete_ssh(plan["range_id"], instance["source"])
        secret_ops.delete_participant_ssh(plan["range_id"], instance["source"])
        secret_ops.delete_rdp_password(plan["range_id"], instance["source"])


def _destroy_network_resources(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Delete the range-owned router/NAT, firewalls, subnets, and (when range-owned) the VPC."""
    # The range-owned Cloud Router (carrying the Cloud NAT) references this range's
    # subnets, so it is torn down before them (PLAT-238). Absent for a `none` range.
    router_nat = plan.get("router_nat")
    if router_nat is not None:
        _delete_resource(
            plan,
            clients,
            clients.routers.get,
            clients.routers.delete,
            "region",
            project=plan["project_id"],
            region=plan["region"],
            router=router_nat["router_name"],
        )

    for firewall in reversed(plan["firewalls"]):
        _delete_resource(
            plan,
            clients,
            clients.firewalls.get,
            clients.firewalls.delete,
            "global",
            project=plan["project_id"],
            firewall=firewall["name"],
        )

    for subnet in reversed(plan["subnets"]):
        _delete_resource(
            plan,
            clients,
            clients.subnetworks.get,
            clients.subnetworks.delete,
            "region",
            project=plan["project_id"],
            region=plan["region"],
            subnetwork=subnet["resource_name"],
        )

    # In shared-vpc mode the range VPC is the pre-existing, platform-peered
    # network and must never be deleted; only per-range subnets/firewalls are torn
    # down above.
    if plan["manage_network"]:
        _delete_resource(
            plan,
            clients,
            clients.networks.get,
            clients.networks.delete,
            "global",
            project=plan["project_id"],
            network=plan["network"]["name"],
        )


def destroy_range_cell(
    request_uuid: str,
    variables: ResourceDict | None,
    *,
    backend: str | None = None,
    config: GCERangeCellConfig | None = None,
    clients: GCEClients | None = None,
    secret_ops: GCEGuestSecretOps | None = None,
    vertex_ops: GCEVertexCredentialOps | None = None,
) -> None:
    """Destroy every GCE resource owned by one range cell."""
    if not variables:
        logger.info("No GCE range variables provided for request %s; nothing to destroy", request_uuid)
        return
    resolved_config = config or load_gce_range_cell_config(backend=backend)
    # The gateway SA email is unused for teardown (resources are deleted by name),
    # but the range's reserved pool slot (ADR-008-R7) is read so the plan renders
    # consistently with provision. The row exists while the range is DESTROYING.
    range_data = get_range_data_by_request_id(request_uuid)
    # Bind the config to this range's realized zone (stored on the row at range
    # creation) before anything reads region/zone. Destroy reconstructs the exact
    # zone the range was placed in -- never a recomputation against a pool that may
    # have changed since -- so it cannot look in the wrong region and strand
    # resources. Empty placement keeps the scalar single-zone config.
    range_host_pool_slot = int(range_data["subnet_index"]) - 1 if range_data.get("subnet_index") is not None else None
    resolved_config = resolve_placement_from_range_data(resolved_config, range_data)
    plan = render_range_cell_plan(
        request_uuid,
        variables,
        resolved_config,
        require_images=False,
        vpn_gateway_pool_slot=range_data.get("vpn_gateway_pool_slot"),
        range_host_pool_slot=range_host_pool_slot,
    )
    resolved_clients = clients or _build_clients()
    resolved_secret_ops = secret_ops or _default_secret_ops()
    resolved_vertex_ops = vertex_ops or _default_vertex_ops()

    # Delete the per-range Vertex agent key first; it is independent of the
    # Compute resources and idempotent, so it converges even on repeated destroy.
    resolved_vertex_ops.delete(plan["range_id"], plan["project_id"])

    _destroy_vpn_gateway(plan, resolved_clients)
    _destroy_instances(plan, resolved_clients, resolved_secret_ops)
    _destroy_network_resources(plan, resolved_clients)


__all__ = ["destroy_range_cell"]
