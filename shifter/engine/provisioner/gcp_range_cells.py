"""Compute Engine range-cell backend for live-fire GCP ranges."""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable

from config import GCERangeCellConfig, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_credentials import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _default_secret_ops,
    _default_vertex_ops,
)
from gcp_range_cell_destroy import destroy_range_cell
from gcp_range_cell_ops import _get_or_none, _wait_for_operation
from gcp_range_cell_outputs import InstanceCredentials, instance_output, range_cell_result, subnet_outputs
from gcp_range_cell_plan import render_range_cell_plan
from gcp_range_cell_resources import (
    HOST_PUBLIC_KEY_METADATA_KEY,
    address_resource,
    firewall_resource,
    instance_resource,
    network_resource,
    openvpn_gateway_address_resource,
    openvpn_gateway_instance_resource,
    subnetwork_resource,
)
from gcp_range_cell_types import (
    FirewallPlan,
    InstancePlan,
    RangeCellPlan,
    ResourceDict,
    SubnetPlan,
)
from log_redact import safe_log_fingerprint
from utils.crypto import generate_ssh_host_keypair

__all__ = [
    "GCEGuestSecretOps",
    "GCEVertexCredentialOps",
    "apply_range_cell",
    "destroy_range_cell",
]

logger = logging.getLogger(__name__)


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


def _existing_label(existing: object, key: str) -> str:
    """Read one label from a dict-like Compute instance response."""
    labels = getattr(existing, "labels", None)
    getter = getattr(labels, "get", None)
    if callable(getter):
        return str(getter(key, "") or "")
    return ""


def _assert_instance_image_binding(existing: object, instance: InstancePlan) -> None:
    """Reject a keyed deterministic VM whose recorded profile differs from the plan."""
    expected_key = instance["image_key"]
    if not expected_key:
        return
    actual_key = _existing_label(existing, "image-key")
    actual_profile = _existing_label(existing, "image-profile")
    if actual_key != expected_key or actual_profile != instance["image_profile_fingerprint"]:
        raise RuntimeError(
            "Existing GCE range instance has an image-profile binding that differs from the current plan; "
            f"ami_key={expected_key!r}. Recreate the range instead of reusing the drifted instance."
        )


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
        return (
            host_secret_ref,
            participant_ssh_secret_ref,
            rdp_password_secret_ref,
            scenario_public_key,
            _host_public_key_from_instance(existing),
        )

    host_private_key, host_public_key = generate_ssh_host_keypair()
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    operation = clients.instances.insert(
        project=plan["project_id"],
        zone=plan["zone"],
        instance_resource=instance_resource(
            plan,
            instance,
            config,
            ssh_public_key=host_management_public_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
        ),
    )
    _wait_for_operation(plan, clients, operation, "zone")
    return host_secret_ref, participant_ssh_secret_ref, rdp_password_secret_ref, scenario_public_key, host_public_key


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


def _external_ip(instance: object) -> str:
    """Return the instance's first NAT external IP, or empty when absent."""
    interfaces = getattr(instance, "network_interfaces", None) or []
    if not interfaces:
        return ""
    access_configs = getattr(interfaces[0], "access_configs", None) or []
    if not access_configs:
        return ""
    return str(getattr(access_configs[0], "nat_i_p", "") or getattr(access_configs[0], "nat_ip", ""))


def _ensure_openvpn_gateway(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
) -> ResourceDict | None:
    """Create/reconcile the request-owned gateway and return non-secret readiness."""
    gateway = plan.get("vpn_gateway")
    if gateway is None:
        return None
    address = _get_or_none(
        clients.addresses.get,
        clients.google_exceptions,
        project=plan["project_id"],
        region=plan["region"],
        address=gateway["address_name"],
    )
    if address is None:
        operation = clients.addresses.insert(
            project=plan["project_id"],
            region=plan["region"],
            address_resource=openvpn_gateway_address_resource(gateway),
        )
        _wait_for_operation(plan, clients, operation, "region")
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=gateway["resource_name"],
    )
    if existing is None:
        operation = clients.instances.insert(
            project=plan["project_id"],
            zone=plan["zone"],
            instance_resource=openvpn_gateway_instance_resource(plan, gateway, config),
        )
        _wait_for_operation(plan, clients, operation, "zone")
        existing = clients.instances.get(
            project=plan["project_id"],
            zone=plan["zone"],
            instance=gateway["resource_name"],
        )
    endpoint = _external_ip(existing)
    if not endpoint:
        raise RuntimeError("GCE OpenVPN gateway has no public endpoint")
    return {
        "endpoint": endpoint,
        "port": 1194,
        "health_endpoint": gateway["private_ip"],
        "health_port": 1195,
        "target_ref": gateway["target_ref"],
        "ready": False,
    }


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
    plan = render_range_cell_plan(request_uuid, variables, resolved_config)
    resolved_clients = clients or _build_clients()
    resolved_secret_ops = secret_ops or _default_secret_ops()
    resolved_vertex_ops = vertex_ops or _default_vertex_ops()
    try:
        instance_outputs = _provision_range_resources(
            plan, resolved_clients, resolved_config, resolved_secret_ops, resolved_vertex_ops
        )
        vpn_gateway = _ensure_openvpn_gateway(plan, resolved_clients, resolved_config)
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
    result: ResourceDict = {
        "subnets": subnet_outputs(plan),
        "instances": instance_outputs,
        "range_cell": closed_result,
    }
    if vpn_gateway is not None:
        result["vpn_gateway"] = vpn_gateway
    return result
