"""Compute Engine range-cell backend for live-fire GCP ranges."""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass

from config import GCERangeCellConfig, load_gce_range_cell_config
from gcp_guest_secrets import (
    delete_rdp_password_secret,
    delete_ssh_secret,
    ensure_rdp_password_secret,
    ensure_ssh_secret,
)
from gcp_range_cell_clients import GCEClients, GoogleExceptions, _build_clients
from gcp_range_cell_ops import _wait_for_operation
from gcp_range_cell_plan import (
    FirewallPlan,
    InstancePlan,
    RangeCellPlan,
    ResourceDict,
    ScenarioInstance,
    SubnetPlan,
    render_range_cell_plan,
)
from gcp_range_cell_resources import (
    HOST_PUBLIC_KEY_METADATA_KEY,
    address_resource,
    firewall_resource,
    instance_resource,
    network_resource,
    subnetwork_resource,
)
from gcp_range_vertex_creds import delete_range_vertex_key, ensure_range_vertex_key
from log_redact import safe_log_fingerprint
from utils.crypto import generate_ssh_host_keypair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GCEGuestSecretOps:
    """Guest credential operations used by the GCE range-cell backend."""

    ensure_ssh: Callable[[int, ScenarioInstance], tuple[str, str]]
    ensure_rdp_password: Callable[[int, ScenarioInstance], tuple[str, str]]
    delete_ssh: Callable[[int, ScenarioInstance], None]
    delete_rdp_password: Callable[[int, ScenarioInstance], None]


def _default_secret_ops() -> GCEGuestSecretOps:
    """Return the production guest-secret operation bindings."""
    return GCEGuestSecretOps(
        ensure_ssh=ensure_ssh_secret,
        ensure_rdp_password=ensure_rdp_password_secret,
        delete_ssh=delete_ssh_secret,
        delete_rdp_password=delete_rdp_password_secret,
    )


@dataclass(frozen=True)
class GCEVertexCredentialOps:
    """Per-range Vertex agent-credential operations used by the GCE backend.

    ``ensure``/``delete`` take the range project id so the SA key and Secret
    Manager secret are managed in the range project, not the control-plane
    project (which may be a deploy-overlay placeholder).
    """

    ensure: Callable[[int, str, str, str], str]
    delete: Callable[[int, str], None]


def _default_vertex_ops() -> GCEVertexCredentialOps:
    """Return the production per-range Vertex credential bindings."""
    return GCEVertexCredentialOps(
        ensure=lambda range_id, sa_email, project_id, host_sa_email: ensure_range_vertex_key(
            range_id, sa_email, project_id=project_id, host_service_account_email=host_sa_email
        ),
        delete=lambda range_id, project_id: delete_range_vertex_key(range_id, project_id=project_id),
    )


def _get_or_none(
    callable_obj: Callable[..., object],
    exceptions: GoogleExceptions,
    **kwargs: object,
) -> object | None:
    """Return a Compute resource or None when the provider reports NotFound."""
    try:
        return callable_obj(**kwargs)
    except exceptions.NotFound:
        return None


def _ensure_network(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Create the range VPC if it is missing."""
    name = plan["network"]["name"]
    existing = _get_or_none(clients.networks.get, clients.google_exceptions, project=plan["project_id"], network=name)
    if existing is not None:
        logger.info("GCE range network exists name_fp=%s", safe_log_fingerprint(name))
        return
    operation = clients.networks.insert(project=plan["project_id"], network_resource=network_resource(plan))
    _wait_for_operation(plan, clients, operation, "global")


def _ensure_subnetwork(plan: RangeCellPlan, clients: GCEClients, subnet: SubnetPlan) -> None:
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
        return
    operation = clients.subnetworks.insert(
        project=plan["project_id"],
        region=plan["region"],
        subnetwork_resource=subnetwork_resource(plan, subnet),
    )
    _wait_for_operation(plan, clients, operation, "region")


def _ensure_firewall(plan: RangeCellPlan, clients: GCEClients, firewall: FirewallPlan) -> None:
    """Create one range firewall rule if it is missing."""
    name = firewall["name"]
    existing = _get_or_none(clients.firewalls.get, clients.google_exceptions, project=plan["project_id"], firewall=name)
    if existing is not None:
        logger.info("GCE range firewall exists name_fp=%s", safe_log_fingerprint(name))
        return
    operation = clients.firewalls.insert(
        project=plan["project_id"], firewall_resource=firewall_resource(plan, firewall)
    )
    _wait_for_operation(plan, clients, operation, "global")


def _ensure_address(plan: RangeCellPlan, clients: GCEClients, instance: InstancePlan) -> None:
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
        return
    operation = clients.addresses.insert(
        project=plan["project_id"],
        region=plan["region"],
        address_resource=address_resource(instance),
    )
    _wait_for_operation(plan, clients, operation, "region")


def _host_public_key_from_instance(existing: object) -> str:
    """Read the provisioner-issued SSH host public key from an existing instance.

    On a reconcile the guest already serves the host key injected at create time,
    so recover it from instance metadata rather than minting a mismatched one.
    """
    metadata = getattr(existing, "metadata", None)
    for item in getattr(metadata, "items", None) or []:
        if getattr(item, "key", None) == HOST_PUBLIC_KEY_METADATA_KEY:
            return str(getattr(item, "value", "") or "")
    return ""


def _ensure_instance(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
    instance: InstancePlan,
    secret_ops: GCEGuestSecretOps,
) -> tuple[str, str | None, str, str]:
    """Create one range instance and its guest credential secrets.

    Returns ``(ssh_secret_ref, rdp_password_secret_ref, ssh_public_key,
    host_public_key)``. The provisioner mints the guest's SSH *host* keypair,
    injects the private half via the guest startup script, and returns the public
    half so the setup runner can seed known_hosts (StrictHostKeyChecking against a
    trusted side-channel key). Neither public key is secret.
    """
    name = instance["resource_name"]
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=name,
    )
    secret_ref, public_key = secret_ops.ensure_ssh(plan["range_id"], instance["source"])
    rdp_password_secret_ref: str | None = None
    if instance["role"] != "dc":
        rdp_password_secret_ref, _password = secret_ops.ensure_rdp_password(plan["range_id"], instance["source"])
    if existing is not None:
        logger.info("GCE range instance exists name_fp=%s", safe_log_fingerprint(name))
        return secret_ref, rdp_password_secret_ref, public_key, _host_public_key_from_instance(existing)

    host_private_key, host_public_key = generate_ssh_host_keypair()
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    operation = clients.instances.insert(
        project=plan["project_id"],
        zone=plan["zone"],
        instance_resource=instance_resource(
            plan,
            instance,
            config,
            ssh_public_key=public_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
        ),
    )
    _wait_for_operation(plan, clients, operation, "zone")
    return secret_ref, rdp_password_secret_ref, public_key, host_public_key


def _instance_output(
    plan: RangeCellPlan,
    instance: InstancePlan,
    *,
    ssh_secret_ref: str,
    rdp_password_secret_ref: str | None,
    ssh_public_key: str,
    host_public_key: str = "",
    config: GCERangeCellConfig,
) -> ResourceDict:
    """Render the provisioner output for one created instance."""
    output: ResourceDict = {
        "uuid": instance["uuid"],
        "name": instance["name"],
        "asset_type": "gce_vm",
        "role": instance["role"],
        "os": instance["os_type"],
        "subnet_name": instance["subnet_name"],
        "instance_id": instance["resource_name"],
        "private_ip": instance["private_ip"],
        "ssh_key_secret_arn": ssh_secret_ref,
        "ssh_username": instance["ssh_username"],
        "public_key": ssh_public_key,
        # Seeds the setup runner's known_hosts (executors/factory reads
        # gcp_host_public_key) for StrictHostKeyChecking against the injected key.
        "gcp_host_public_key": host_public_key,
        "gcp_host_ssh_username": instance["host_ssh_username"],
        "gcp_host_ssh_port": instance["ssh_port"],
        "gcp_project_id": plan["project_id"],
        "gcp_region": plan["region"],
        "gcp_zone": plan["zone"],
        "gcp_network_name": plan["network"]["name"],
        "gcp_network_self_link": plan["network"]["self_link"],
        "gcp_subnetwork_name": instance["subnet_resource_name"],
        "gcp_subnetwork_self_link": instance["subnetwork_link"],
        "gcp_instance_name": instance["resource_name"],
        "gcp_address_name": instance["address_name"],
        "gcp_network_tags": instance["tags"],
        "gcp_service_account_email": config.service_account_email,
    }
    if rdp_password_secret_ref:
        output["rdp_password_secret_arn"] = rdp_password_secret_ref
        output["gcp_rdp_password_secret_ref"] = rdp_password_secret_ref
    return output


def _subnet_outputs(plan: RangeCellPlan) -> dict[str, ResourceDict]:
    """Render provisioner subnet outputs keyed by scenario subnet name."""
    return {
        subnet["name"]: {
            "uuid": subnet["uuid"],
            "subnet_id": subnet["resource_name"],
            "subnet_cidr": subnet["cidr"],
            "gcp_network_name": plan["network"]["name"],
            "gcp_network_self_link": plan["network"]["self_link"],
            "gcp_subnetwork_name": subnet["resource_name"],
            "gcp_subnetwork_self_link": subnet["self_link"],
            "gcp_region": plan["region"],
            "gcp_gateway_reserved": True,
            "gcp_instance_ip_assignments": subnet["ip_assignments"],
        }
        for subnet in plan["subnets"]
    }


def _provision_range_resources(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
    secret_ops: GCEGuestSecretOps,
    vertex_ops: GCEVertexCredentialOps,
) -> list[ResourceDict]:
    """Create the network, subnets, firewalls, instances, and per-range creds.

    The range VPC is created only when the range owns it (vpc-per-range); in
    shared-vpc mode the pre-existing platform-peered VPC is reused and only the
    per-range subnets/firewalls/instances are created here.
    """
    if config.vertex_service_account_email:
        vertex_ops.ensure(
            plan["range_id"],
            config.vertex_service_account_email,
            plan["project_id"],
            config.service_account_email,
        )
    if plan["manage_network"]:
        _ensure_network(plan, clients)
    for subnet in plan["subnets"]:
        _ensure_subnetwork(plan, clients, subnet)
    for firewall in plan["firewalls"]:
        _ensure_firewall(plan, clients, firewall)
    instance_outputs: list[ResourceDict] = []
    for instance in plan["instances"]:
        _ensure_address(plan, clients, instance)
        ssh_secret_ref, rdp_password_secret_ref, ssh_public_key, host_public_key = _ensure_instance(
            plan, clients, config, instance, secret_ops
        )
        instance_outputs.append(
            _instance_output(
                plan,
                instance,
                ssh_secret_ref=ssh_secret_ref,
                rdp_password_secret_ref=rdp_password_secret_ref,
                ssh_public_key=ssh_public_key,
                host_public_key=host_public_key,
                config=config,
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
    resolved_clients = clients or _build_clients()
    resolved_secret_ops = secret_ops or _default_secret_ops()
    resolved_vertex_ops = vertex_ops or _default_vertex_ops()
    plan = render_range_cell_plan(request_uuid, variables, resolved_config)
    try:
        instance_outputs = _provision_range_resources(
            plan, resolved_clients, resolved_config, resolved_secret_ops, resolved_vertex_ops
        )
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
    return {"subnets": _subnet_outputs(plan), "instances": instance_outputs}


def _delete_resource(
    plan: RangeCellPlan,
    clients: GCEClients,
    getter: Callable[..., object],
    deleter: Callable[..., object],
    scope: str,
    **kwargs: object,
) -> None:
    """Delete a Compute resource when it exists."""
    name = str(next(reversed(kwargs.values())))
    existing = _get_or_none(getter, clients.google_exceptions, **kwargs)
    if existing is None:
        return
    operation = deleter(**kwargs)
    _wait_for_operation(plan, clients, operation, scope)
    logger.info("Deleted GCE range resource name_fp=%s", safe_log_fingerprint(name))


def destroy_range_cell(
    request_uuid: str,
    variables: ResourceDict | None,
    *,
    config: GCERangeCellConfig | None = None,
    clients: GCEClients | None = None,
    secret_ops: GCEGuestSecretOps | None = None,
    vertex_ops: GCEVertexCredentialOps | None = None,
) -> None:
    """Destroy every GCE resource owned by one range cell."""
    if not variables:
        logger.info("No GCE range variables provided for request %s; nothing to destroy", request_uuid)
        return
    resolved_config = config or load_gce_range_cell_config()
    resolved_clients = clients or _build_clients()
    resolved_secret_ops = secret_ops or _default_secret_ops()
    resolved_vertex_ops = vertex_ops or _default_vertex_ops()
    plan = render_range_cell_plan(request_uuid, variables, resolved_config, require_images=False)

    # Delete the per-range Vertex agent key first; it is independent of the
    # Compute resources and idempotent, so it converges even on repeated destroy.
    resolved_vertex_ops.delete(plan["range_id"], plan["project_id"])

    for instance in reversed(plan["instances"]):
        _delete_resource(
            plan,
            resolved_clients,
            resolved_clients.instances.get,
            resolved_clients.instances.delete,
            "zone",
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance["resource_name"],
        )
        _delete_resource(
            plan,
            resolved_clients,
            resolved_clients.addresses.get,
            resolved_clients.addresses.delete,
            "region",
            project=plan["project_id"],
            region=plan["region"],
            address=instance["address_name"],
        )
        resolved_secret_ops.delete_ssh(plan["range_id"], instance["source"])
        resolved_secret_ops.delete_rdp_password(plan["range_id"], instance["source"])

    for firewall in reversed(plan["firewalls"]):
        _delete_resource(
            plan,
            resolved_clients,
            resolved_clients.firewalls.get,
            resolved_clients.firewalls.delete,
            "global",
            project=plan["project_id"],
            firewall=firewall["name"],
        )

    for subnet in reversed(plan["subnets"]):
        _delete_resource(
            plan,
            resolved_clients,
            resolved_clients.subnetworks.get,
            resolved_clients.subnetworks.delete,
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
            resolved_clients,
            resolved_clients.networks.get,
            resolved_clients.networks.delete,
            "global",
            project=plan["project_id"],
            network=plan["network"]["name"],
        )
