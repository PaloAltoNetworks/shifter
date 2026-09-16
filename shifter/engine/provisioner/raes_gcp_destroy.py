"""Teardown of every GCE resource owned by one RAES range cell (ADR-031/032).

Extracted from ``raes_gcp_apply.py`` (Sonar S104). Destroy is reconstructive:
the serialized plan yields deterministic resource names, so teardown rebuilds
the plan (with a default image profile, since only names are needed) and
deletes every owned resource -- no persisted output is required.

``raes_gcp_apply.py`` imports :func:`destroy_raes_range_cell` back for its own
failed-apply cleanup path, so this module must not import from
``raes_gcp_apply`` (that would be circular); the shared SSH-secret contract
(``RaesGceSecretOps``) lives in the leaf module ``raes_gcp_secret_ops``, which
both this module and ``raes_gcp_apply`` import from independently.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_ops import _delete_resource
from gcp_range_cell_types import InstancePlan, RangeCellPlan
from raes_account_credentials import (
    RaesAccountCredentialOps,
    default_account_credential_ops,
    delete_instance_account_credentials,
)
from raes_active_directory import (
    RaesDirectorySecretOps,
    default_directory_secret_ops,
    delete_raes_directory_secrets,
)
from raes_gcp_plan import build_raes_range_cell_plan
from raes_gcp_secret_ops import RaesGceSecretOps, _default_secret_ops
from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanNode

__all__ = ["RaesGceDestroyOptions", "destroy_raes_range_cell"]


@dataclass(frozen=True)
class RaesGceDestroyOptions:
    """Optional account and directory cleanup bindings for RAES teardown."""

    config: GCERangeCellConfig | None = None
    clients: GCEClients | None = None
    secret_ops: RaesGceSecretOps | None = None
    account_secret_ops: RaesAccountCredentialOps | None = None
    directory_secret_ops: RaesDirectorySecretOps | None = None
    allocated_network_cidr: str | None = None
    reconstruct_without_allocation: bool = False


@dataclass(frozen=True)
class _RaesGceDestroyRuntime:
    """Resolved non-optional bindings shared by RAES resource teardown."""

    config: GCERangeCellConfig
    clients: GCEClients
    secret_ops: RaesGceSecretOps
    account_secret_ops: RaesAccountCredentialOps
    directory_secret_ops: RaesDirectorySecretOps


def _default_destroy_profile(_node: RaesPlanNode) -> GCERangeImageProfile:
    """Image resolver used for destroy: teardown deletes by name, so no image."""
    return GCERangeImageProfile()


def _destroy_runtime(
    options: RaesGceDestroyOptions,
) -> _RaesGceDestroyRuntime:
    """Resolve optional teardown bindings exactly once."""
    return _RaesGceDestroyRuntime(
        config=options.config or load_gce_range_cell_config(),
        clients=options.clients or _build_clients(),
        secret_ops=options.secret_ops or _default_secret_ops(),
        account_secret_ops=options.account_secret_ops or default_account_credential_ops(),
        directory_secret_ops=options.directory_secret_ops or default_directory_secret_ops(),
    )


def destroy_raes_range_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    options: RaesGceDestroyOptions | None = None,
) -> None:
    """Destroy every GCE resource owned by one RAES range cell."""
    resolved_options = options or RaesGceDestroyOptions()
    runtime = _destroy_runtime(resolved_options)
    plan = build_raes_range_cell_plan(
        request_uuid,
        range_id,
        raes_plan,
        _default_destroy_profile,
        runtime.config,
        allocated_network_cidr=resolved_options.allocated_network_cidr,
        reconstruct_for_teardown=resolved_options.reconstruct_without_allocation,
    )
    _destroy_instances(plan, raes_plan, runtime)
    delete_raes_directory_secrets(plan["range_id"], raes_plan, runtime.directory_secret_ops)
    _destroy_network_resources(plan, runtime.clients)


def _destroy_instances(
    plan: RangeCellPlan,
    raes_plan: RaesPlan,
    runtime: _RaesGceDestroyRuntime,
) -> None:
    """Delete instances, addresses, and their deterministic guest secrets."""
    for instance in reversed(plan["instances"]):
        _delete_resource(
            plan,
            runtime.clients,
            runtime.clients.instances.get,
            runtime.clients.instances.delete,
            "zone",
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance["resource_name"],
        )
        _delete_resource(
            plan,
            runtime.clients,
            runtime.clients.addresses.get,
            runtime.clients.addresses.delete,
            "region",
            project=plan["project_id"],
            region=plan["region"],
            address=instance["address_name"],
        )
        runtime.secret_ops.delete_ssh(plan["range_id"], instance["uuid"])
        delete_instance_account_credentials(
            plan["range_id"],
            instance["uuid"],
            _instance_accounts(raes_plan, instance),
            runtime.account_secret_ops,
        )


def _instance_accounts(raes_plan: RaesPlan, instance: InstancePlan) -> tuple[RaesPlanAccount, ...]:
    """Return local-only account placements belonging to one instance's node."""
    node_address = str(instance["uuid"]).rsplit("#", 1)[0]
    return tuple(
        account
        for account in raes_plan.accounts
        if account.target_address == node_address and account.domain_ref is None and account.domain_id is None
    )


def _destroy_network_resources(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Delete the range-owned router/NAT, firewalls, subnets, and an owned network in order."""
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

    # In shared-vpc mode the range VPC is the pre-existing, platform-peered network
    # and must never be deleted; only per-range subnets/firewalls are torn down.
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
