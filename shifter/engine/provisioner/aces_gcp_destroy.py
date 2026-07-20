"""Teardown of every GCE resource owned by one ACES range cell (ADR-031/032).

Extracted from ``aces_gcp_apply.py`` (Sonar S104). Destroy is reconstructive:
the serialized plan yields deterministic resource names, so teardown rebuilds
the plan (with a default image profile, since only names are needed) and
deletes every owned resource -- no persisted output is required.

``aces_gcp_apply.py`` imports :func:`destroy_aces_range_cell` back for its own
failed-apply cleanup path, so this module must not import from
``aces_gcp_apply`` (that would be circular); the shared SSH-secret contract
(``AcesGceSecretOps``) lives in the leaf module ``aces_gcp_secret_ops``, which
both this module and ``aces_gcp_apply`` import from independently.
"""

from __future__ import annotations

from dataclasses import dataclass

from aces_account_credentials import (
    AcesAccountCredentialOps,
    default_account_credential_ops,
    delete_instance_account_credentials,
)
from aces_active_directory import (
    AcesDirectorySecretOps,
    default_directory_secret_ops,
    delete_aces_directory_secrets,
)
from aces_gcp_plan import build_aces_range_cell_plan
from aces_gcp_secret_ops import AcesGceSecretOps, _default_secret_ops
from aces_plan import AcesPlan, AcesPlanAccount, AcesPlanNode
from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_ops import _delete_resource
from gcp_range_cell_types import InstancePlan, RangeCellPlan

__all__ = ["AcesGceDestroyOptions", "destroy_aces_range_cell"]


@dataclass(frozen=True)
class AcesGceDestroyOptions:
    """Optional account and directory cleanup bindings for ACES teardown."""

    account_secret_ops: AcesAccountCredentialOps | None = None
    directory_secret_ops: AcesDirectorySecretOps | None = None


@dataclass(frozen=True)
class _AcesGceDestroyRuntime:
    """Resolved non-optional bindings shared by ACES resource teardown."""

    config: GCERangeCellConfig
    clients: GCEClients
    secret_ops: AcesGceSecretOps
    account_secret_ops: AcesAccountCredentialOps
    directory_secret_ops: AcesDirectorySecretOps


def _default_destroy_profile(_node: AcesPlanNode) -> GCERangeImageProfile:
    """Image resolver used for destroy: teardown deletes by name, so no image."""
    return GCERangeImageProfile()


def _destroy_runtime(
    config: GCERangeCellConfig | None,
    clients: GCEClients | None,
    secret_ops: AcesGceSecretOps | None,
    options: AcesGceDestroyOptions,
) -> _AcesGceDestroyRuntime:
    """Resolve optional teardown bindings exactly once."""
    return _AcesGceDestroyRuntime(
        config=config or load_gce_range_cell_config(),
        clients=clients or _build_clients(),
        secret_ops=secret_ops or _default_secret_ops(),
        account_secret_ops=options.account_secret_ops or default_account_credential_ops(),
        directory_secret_ops=options.directory_secret_ops or default_directory_secret_ops(),
    )


def destroy_aces_range_cell(
    request_uuid: str,
    range_id: int,
    aces_plan: AcesPlan,
    config: GCERangeCellConfig | None = None,
    clients: GCEClients | None = None,
    secret_ops: AcesGceSecretOps | None = None,
    options: AcesGceDestroyOptions | None = None,
) -> None:
    """Destroy every GCE resource owned by one ACES range cell."""
    runtime = _destroy_runtime(config, clients, secret_ops, options or AcesGceDestroyOptions())
    plan = build_aces_range_cell_plan(request_uuid, range_id, aces_plan, _default_destroy_profile, runtime.config)
    _destroy_instances(plan, aces_plan, runtime)
    delete_aces_directory_secrets(plan["range_id"], aces_plan, runtime.directory_secret_ops)
    _destroy_network_resources(plan, runtime.clients)


def _destroy_instances(
    plan: RangeCellPlan,
    aces_plan: AcesPlan,
    runtime: _AcesGceDestroyRuntime,
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
            _instance_accounts(aces_plan, instance),
            runtime.account_secret_ops,
        )


def _instance_accounts(aces_plan: AcesPlan, instance: InstancePlan) -> tuple[AcesPlanAccount, ...]:
    """Return local-only account placements belonging to one instance's node."""
    node_address = str(instance["uuid"]).rsplit("#", 1)[0]
    return tuple(
        account
        for account in aces_plan.accounts
        if account.target_address == node_address and account.domain_ref is None and account.domain_id is None
    )


def _destroy_network_resources(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Delete firewalls, subnets, and an owned per-range network in dependency order."""
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
