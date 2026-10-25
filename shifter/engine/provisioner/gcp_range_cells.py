"""Compute Engine range-cell backend for live-fire GCP ranges."""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Iterable, Mapping

from config import GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST, GCERangeCellConfig, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_credentials import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _default_secret_ops,
    _default_vertex_ops,
)
from gcp_range_cell_destroy import destroy_range_cell
from gcp_range_cell_host_binding import (
    _assert_instance_image_binding,
    _assert_preconfigured_host_binding,
    _host_public_key_from_instance,
)
from gcp_range_cell_ops import _get_or_none, _wait_for_operation, insert_instance_with_machine_image_retry
from gcp_range_cell_outputs import InstanceCredentials, instance_output, range_cell_result, subnet_outputs
from gcp_range_cell_plan import render_range_cell_plan
from gcp_range_cell_resources import (
    address_resource,
    firewall_resource,
    instance_resource,
    log_config_matches,
    nat_log_config,
    network_resource,
    provider_field,
    router_nat_resource,
    subnetwork_log_config,
    subnetwork_resource,
)
from gcp_range_cell_shared_nat import assert_shared_nat_capacity, ensure_shared_nat
from gcp_range_cell_types import (
    FirewallPlan,
    InstancePlan,
    RangeCellPlan,
    ResourceDict,
    SubnetPlan,
)
from log_redact import safe_log_fingerprint
from provisioner_db import get_range_data_by_request_id
from range_placement import resolve_placement_from_range_data
from utils.crypto import generate_ssh_host_keypair

__all__ = [
    "GCEGuestSecretOps",
    "GCEVertexCredentialOps",
    "apply_range_cell",
    "destroy_range_cell",
]

logger = logging.getLogger(__name__)


def _ensure_network(plan: RangeCellPlan, clients: GCEClients) -> bool:
    """Create the range VPC if it is missing."""
    name = plan["network"]["name"]
    existing = _get_or_none(clients.networks.get, clients.google_exceptions, project=plan["project_id"], network=name)
    if existing is not None:
        logger.info("GCE range network exists name_fp=%s", safe_log_fingerprint(name))
        return False
    operation = clients.networks.insert(project=plan["project_id"], network_resource=network_resource(plan))
    _wait_for_operation(plan, clients, operation, "global")
    return True


def _ensure_subnetwork(plan: RangeCellPlan, clients: GCEClients, subnet: SubnetPlan) -> bool:
    """Create a range subnetwork if it is missing."""
    name = subnet["resource_name"]
    existing = _get_or_none(
        clients.subnetworks.get,
        clients.google_exceptions,
        project=plan["project_id"],
        region=plan["region"],
        subnetwork=name,
    )
    if existing is not None:
        logger.info("GCE range subnetwork exists name_fp=%s", safe_log_fingerprint(name))
        _converge_subnetwork_log_config(plan, clients, name, existing)
        return False
    operation = clients.subnetworks.insert(
        project=plan["project_id"],
        region=plan["region"],
        subnetwork_resource=subnetwork_resource(plan, subnet),
    )
    _wait_for_operation(plan, clients, operation, "region")
    return True


def _converge_subnetwork_log_config(plan: RangeCellPlan, clients: GCEClients, name: str, existing: object) -> None:
    """Patch an owned subnetwork whose flow-log config drifted from the plan (#2535).

    Existence is not compliance: a replay after a partial create, or after an operator
    policy change, must leave the subnet with the planned flow logging.
    """
    desired = subnetwork_log_config(plan)
    if log_config_matches(provider_field(existing, "log_config"), desired):
        return
    logger.info("GCE range subnetwork flow-log drift; patching name_fp=%s", safe_log_fingerprint(name))
    operation = clients.subnetworks.patch(
        project=plan["project_id"],
        region=plan["region"],
        subnetwork=name,
        subnetwork_resource={"fingerprint": provider_field(existing, "fingerprint"), "log_config": desired},
    )
    _wait_for_operation(plan, clients, operation, "region")


def _converge_router_nat_log_config(plan: RangeCellPlan, clients: GCEClients, name: str, existing: object) -> None:
    """Patch an owned range router whose NAT logging drifted from the plan (#2535).

    The range-owned router is deterministic from the plan, so the patch restores the
    planned gateway (scope and logging) rather than editing one field in place.
    """
    desired = nat_log_config(plan)
    nat_name = plan["router_nat"]["nat_name"]
    gateways = provider_field(existing, "nats")
    items = gateways if isinstance(gateways, Iterable) and not isinstance(gateways, str | bytes | Mapping) else ()
    gateway = next((item for item in items if provider_field(item, "name") == nat_name), None)
    if gateway is not None and log_config_matches(provider_field(gateway, "log_config"), desired):
        return
    logger.info("GCE range router/NAT logging drift; patching name_fp=%s", safe_log_fingerprint(name))
    operation = clients.routers.patch(
        project=plan["project_id"],
        region=plan["region"],
        router=name,
        router_resource={"nats": router_nat_resource(plan)["nats"]},
    )
    _wait_for_operation(plan, clients, operation, "region")


def _ensure_firewall(plan: RangeCellPlan, clients: GCEClients, firewall: FirewallPlan) -> bool:
    """Create one range firewall rule, or reconcile an existing rule to the plan.

    Name existence is not correctness (#1711 / ADR-039-R9): a rule that already
    exists may carry a stale, broader body -- most importantly a legacy combined
    ``*-mgmt`` rule that opened participant RDP from the broad management source
    before this issue split participant access onto its own dedicated-source rule.
    Trusting the name would leave that broad rule live on already-active cells.
    So an existing rule is patched to converge on the freshly rendered body rather
    than skipped. Patch is idempotent: an already-matching rule is a no-op update.
    """
    name = firewall["name"]
    body = firewall_resource(plan, firewall)
    existing = _get_or_none(clients.firewalls.get, clients.google_exceptions, project=plan["project_id"], firewall=name)
    if existing is None:
        operation = clients.firewalls.insert(project=plan["project_id"], firewall_resource=body)
        _wait_for_operation(plan, clients, operation, "global")
        return True
    logger.info("GCE range firewall reconcile name_fp=%s", safe_log_fingerprint(name))
    operation = clients.firewalls.patch(project=plan["project_id"], firewall=name, firewall_resource=body)
    _wait_for_operation(plan, clients, operation, "global")
    return False


def _ensure_router_nat(plan: RangeCellPlan, clients: GCEClients) -> bool:
    """Create the range-owned Cloud Router + NAT if the plan carries one (PLAT-238).

    Present only for a non-``none`` range; a zero-egress range has no ``router_nat``
    element and therefore no NAT path. Idempotent: an existing router of the same
    name is kept, and only its NAT logging is converged to the plan (#2535).
    """
    shared_nat = plan.get("shared_nat")
    if shared_nat is not None:
        ensure_shared_nat(plan, clients)
    router_nat = plan.get("router_nat")
    # A shared-NAT range delegates egress to the shared router; a zero-egress
    # range carries no router_nat. Neither owns a range-scoped router here.
    if shared_nat is not None or router_nat is None:
        return False
    name = router_nat["router_name"]
    existing = _get_or_none(
        clients.routers.get,
        clients.google_exceptions,
        project=plan["project_id"],
        region=plan["region"],
        router=name,
    )
    if existing is not None:
        logger.info("GCE range router/NAT exists name_fp=%s", safe_log_fingerprint(name))
        _converge_router_nat_log_config(plan, clients, name, existing)
        return False
    operation = clients.routers.insert(
        project=plan["project_id"],
        region=plan["region"],
        router_resource=router_nat_resource(plan),
    )
    _wait_for_operation(plan, clients, operation, "region")
    return True


def _ensure_address(plan: RangeCellPlan, clients: GCEClients, instance: InstancePlan) -> bool:
    """Reserve an internal address for one range instance."""
    name = instance["address_name"]
    existing = _get_or_none(
        clients.addresses.get,
        clients.google_exceptions,
        project=plan["project_id"],
        region=plan["region"],
        address=name,
    )
    if existing is not None:
        logger.info("GCE range address exists name_fp=%s", safe_log_fingerprint(name))
        return False
    operation = clients.addresses.insert(
        project=plan["project_id"],
        region=plan["region"],
        address_resource=address_resource(instance),
    )
    _wait_for_operation(plan, clients, operation, "region")
    return True


def _ensure_attached_disks_auto_delete(
    plan: RangeCellPlan,
    clients: GCEClients,
    instance_name: str,
    existing: object,
) -> None:
    """Make every machine-image-cloned disk range-owned and idempotently deletable."""
    for disk in getattr(existing, "disks", None) or []:
        if bool(getattr(disk, "auto_delete", False)):
            continue
        device_name = str(getattr(disk, "device_name", "") or "")
        if not device_name:
            raise RuntimeError("GCE range instance has an attached disk without a device name")
        operation = clients.instances.set_disk_auto_delete(
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance_name,
            device_name=device_name,
            auto_delete=True,
        )
        _wait_for_operation(plan, clients, operation, "zone")


def _insert_instance(
    plan: RangeCellPlan,
    clients: GCEClients,
    instance: InstancePlan,
    instance_body: ResourceDict,
) -> None:
    """Insert an instance and finalize ownership of machine-image disks."""
    insert_kwargs: dict[str, object] = {
        "project": plan["project_id"],
        "zone": plan["zone"],
        "instance_resource": instance_body,
    }
    machine_image = instance["profile"].source_machine_image
    if not machine_image:
        operation = clients.instances.insert(**insert_kwargs)
        _wait_for_operation(plan, clients, operation, "zone")
        return
    # The generated Compute client does not expose source_machine_image as a
    # flattened keyword. It is accepted only through InsertInstanceRequest.
    insert_request = {**insert_kwargs, "source_machine_image": machine_image}
    raced = insert_instance_with_machine_image_retry(plan, clients, insert_request, instance["resource_name"])
    if raced is not None:
        # A rate-limited operation raced a successful one; finalize the instance a
        # prior attempt created instead of issuing a duplicate insert.
        _assert_instance_image_binding(raced, instance)
        _ensure_attached_disks_auto_delete(plan, clients, instance["resource_name"], raced)
        return
    created = clients.instances.get(
        project=plan["project_id"],
        zone=plan["zone"],
        instance=instance["resource_name"],
    )
    _ensure_attached_disks_auto_delete(plan, clients, instance["resource_name"], created)


def _ensure_instance(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
    instance: InstancePlan,
    secret_ops: GCEGuestSecretOps,
) -> tuple[str, str | None, str | None, str, str]:
    """Create one range instance and its guest credential secrets.

    The host-management SSH key is always separate from a declared participant
    SSH key.  The latter is the only SSH credential eligible for the closed
    access result.  The provisioner also mints the guest's SSH host keypair and
    returns its public half for strict host-key verification.
    """
    name = instance["resource_name"]
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=name,
    )
    if existing is not None:
        _assert_preconfigured_host_binding(existing, plan, instance)
        _assert_instance_image_binding(existing, instance)
    host_secret_ref, host_management_public_key = secret_ops.ensure_ssh(plan["range_id"], instance["source"])
    access_channels = set(instance["participant_access_channels"])
    participant_ssh_secret_ref: str | None = None
    scenario_public_key = host_management_public_key
    if "ssh" in access_channels:
        participant_ssh_secret_ref, participant_public_key = secret_ops.ensure_participant_ssh(
            plan["range_id"], instance["source"]
        )
        scenario_public_key = participant_public_key
        if instance["host_ssh_username"] == instance["ssh_username"]:
            # Native guests use one OS account for setup and participant SSH.
            # Preserve both keys so a reconcile can still use the private
            # management key while only the participant key is brokerable.
            scenario_public_key = f"{host_management_public_key}\n{participant_public_key}"
    rdp_password_secret_ref: str | None = None
    if instance["role"] != "dc":
        rdp_password_secret_ref, _password = secret_ops.ensure_rdp_password(plan["range_id"], instance["source"])
    if existing is not None:
        logger.info("GCE range instance exists name_fp=%s", safe_log_fingerprint(name))
        if instance["profile"].bootstrap_capability == GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
            _ensure_attached_disks_auto_delete(plan, clients, name, existing)
        return (
            host_secret_ref,
            participant_ssh_secret_ref,
            rdp_password_secret_ref,
            scenario_public_key,
            _host_public_key_from_instance(existing),
        )

    host_private_key, host_public_key = generate_ssh_host_keypair()
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    _insert_instance(
        plan,
        clients,
        instance,
        instance_resource(
            plan,
            instance,
            config,
            ssh_public_key=host_management_public_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
        ),
    )
    return host_secret_ref, participant_ssh_secret_ref, rdp_password_secret_ref, scenario_public_key, host_public_key


def _provision_range_resources(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
    secret_ops: GCEGuestSecretOps,
) -> list[ResourceDict]:
    """Create the network, subnets, firewalls, instances, and per-range creds.

    The range VPC is created only when the range owns it (vpc-per-range); in
    shared-vpc mode the pre-existing platform-peered VPC is reused and only the
    per-range subnets/firewalls/instances are created here.
    """
    assert_shared_nat_capacity(plan, clients)
    if plan["manage_network"]:
        _ensure_network(plan, clients)
    for subnet in plan["subnets"]:
        _ensure_subnetwork(plan, clients, subnet)
    _ensure_router_nat(plan, clients)
    for firewall in plan["firewalls"]:
        _ensure_firewall(plan, clients, firewall)
    instance_outputs: list[ResourceDict] = []
    for instance in plan["instances"]:
        _ensure_address(plan, clients, instance)
        (
            host_ssh_secret_ref,
            participant_ssh_secret_ref,
            rdp_password_secret_ref,
            ssh_public_key,
            host_public_key,
        ) = _ensure_instance(plan, clients, config, instance, secret_ops)
        instance_outputs.append(
            instance_output(
                plan,
                instance,
                InstanceCredentials(
                    host_ssh_secret_ref=host_ssh_secret_ref,
                    participant_ssh_secret_ref=participant_ssh_secret_ref,
                    rdp_password_secret_ref=rdp_password_secret_ref,
                    ssh_public_key=ssh_public_key,
                    host_public_key=host_public_key,
                ),
                config,
            )
        )
    return instance_outputs


def apply_range_cell(
    request_uuid: str,
    variables: ResourceDict,
    *,
    config: GCERangeCellConfig | None = None,
    clients: GCEClients | None = None,
    secret_ops: GCEGuestSecretOps | None = None,
    vertex_ops: GCEVertexCredentialOps | None = None,
    cleanup_range_cell: Callable[[str, ResourceDict | None], None] | None = None,
) -> ResourceDict:
    """Create or reconcile a live-fire GCE range cell and return provisioner outputs."""
    resolved_config = config or load_gce_range_cell_config()
    # Validate the closed contract and scenario binding before constructing any
    # provider or secret client, let alone mutating a cloud resource.
    range_data = get_range_data_by_request_id(request_uuid)
    # Bind the config to this range's realized zone (chosen at range creation and
    # stored on the row) before anything reads region/zone. Empty placement keeps
    # the scalar single-zone config. Never recomputed from the pool here.
    range_host_pool_slot = int(range_data["subnet_index"]) - 1 if range_data.get("subnet_index") is not None else None
    resolved_config = resolve_placement_from_range_data(resolved_config, range_data)
    plan = render_range_cell_plan(
        request_uuid,
        variables,
        resolved_config,
        range_host_pool_slot=range_host_pool_slot,
    )
    resolved_clients = clients or _build_clients()
    resolved_secret_ops = secret_ops or _default_secret_ops()
    resolved_vertex_ops = vertex_ops or _default_vertex_ops()
    try:
        instance_outputs = _provision_range_resources(plan, resolved_clients, resolved_config, resolved_secret_ops)
        closed_result = range_cell_result(variables, plan, instance_outputs)
    except Exception:
        logger.exception("GCE range-cell apply failed; attempting cleanup request_id=%s", request_uuid)
        cleanup = cleanup_range_cell or (
            lambda cleanup_request_uuid, cleanup_variables: destroy_range_cell(
                cleanup_request_uuid,
                cleanup_variables,
                config=resolved_config,
                clients=resolved_clients,
                secret_ops=resolved_secret_ops,
                vertex_ops=resolved_vertex_ops,
            )
        )
        cleanup(request_uuid, variables)
        raise
    return {
        "subnets": subnet_outputs(plan),
        "instances": instance_outputs,
        "range_cell": closed_result,
    }
