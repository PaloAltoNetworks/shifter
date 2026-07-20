"""Output renderers for realized GCE range-cell resources."""

from __future__ import annotations

from dataclasses import dataclass

from shared.range_cells import RangeCellContractError, build_gcp_vm_range_cell_result

from config import GCERangeCellConfig
from gcp_range_cell_plan import InstancePlan, RangeCellPlan, ResourceDict


@dataclass(frozen=True)
class InstanceCredentials:
    """Credential references and public material emitted for one guest."""

    host_ssh_secret_ref: str
    participant_ssh_secret_ref: str | None
    rdp_password_secret_ref: str | None
    ssh_public_key: str
    host_public_key: str = ""


def instance_output(
    plan: RangeCellPlan,
    instance: InstancePlan,
    credentials: InstanceCredentials,
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
        # The scenario-declared participant access channels for this member: the
        # closed realized access binding the portal authorizes against (issue
        # #1349), so participant access is granted from the declared target/channel
        # binding rather than mere credential presence. Empty when the scenario
        # authorized none.
        "participant_access_channels": list(instance["participant_access_channels"]),
        # Participant-facing fields are populated only when the scenario
        # explicitly authorized the corresponding channel.
        "ssh_key_secret_arn": credentials.participant_ssh_secret_ref or "",
        "ssh_username": instance["ssh_username"],
        "public_key": credentials.ssh_public_key,
        # Seeds the setup runner's known_hosts (executors/factory reads
        # gcp_host_public_key) for StrictHostKeyChecking against the injected key.
        "gcp_host_public_key": credentials.host_public_key,
        "gcp_host_ssh_key_secret_ref": credentials.host_ssh_secret_ref,
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
        "gcp_service_account_email": config.service_account_email if instance["attach_service_account"] else "",
    }
    if credentials.rdp_password_secret_ref:
        output["gcp_bootstrap_rdp_password_secret_ref"] = credentials.rdp_password_secret_ref
        if "rdp" in instance["participant_access_channels"]:
            output["rdp_password_secret_arn"] = credentials.rdp_password_secret_ref
    return output


def subnet_outputs(plan: RangeCellPlan) -> dict[str, ResourceDict]:
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


def range_cell_result(
    request: ResourceDict,
    plan: RangeCellPlan,
    instance_outputs: list[ResourceDict],
) -> ResourceDict:
    """Render the closed outer lifecycle, membership, and logical-access result."""
    subnet_refs = {subnet["name"]: subnet["uuid"] for subnet in plan["subnets"]}
    outputs_by_ref = {str(output.get("uuid", "")): output for output in instance_outputs}
    members: list[dict[str, object]] = []
    access: list[dict[str, object]] = []
    for instance in plan["instances"]:
        authored_ref = instance["uuid"]
        output = outputs_by_ref.get(authored_ref)
        if output is None:
            raise RuntimeError(f"GCE range-cell output is missing authored member: {authored_ref}")
        members.append(
            {
                "authored_ref": authored_ref,
                "resource_id": (
                    f"projects/{plan['project_id']}/zones/{plan['zone']}/instances/{instance['resource_name']}"
                ),
                "subnet_ref": subnet_refs[instance["subnet_name"]],
                "lifecycle_state": "ready",
            }
        )
        for channel in instance["participant_access_channels"]:
            credential_field = "ssh_key_secret_arn" if channel == "ssh" else "rdp_password_secret_arn"
            credential_ref = str(output.get(credential_field, ""))
            if not credential_ref:
                raise RangeCellContractError(
                    "declared participant access is missing a participant credential reference: "
                    f"{authored_ref}/{channel}"
                )
            access.append(
                {
                    "target_ref": authored_ref,
                    "channel": channel,
                    "address": instance["private_ip"],
                    "port": 22 if channel == "ssh" else 3389,
                    "credential_ref": credential_ref,
                }
            )
    return build_gcp_vm_range_cell_result(
        request,
        cell_id=f"gcp:{plan['project_id']}:{plan['region']}:{plan['range_id']}",
        members=members,
        access=access,
    )


__all__ = ["InstanceCredentials", "instance_output", "range_cell_result", "subnet_outputs"]
