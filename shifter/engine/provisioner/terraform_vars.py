"""Terraform variable builders for Shifter range provisioning.

Extracted from ``terraform_ops.py`` (Sonar S104). Maps a hydrated
range spec into the inputs the Terraform range module expects:
per-instance dicts, per-subnet nested config, NGFW attachment
resolution, AWS-only AMI / instance-profile / Secrets Manager CMK
variables, and the top-level ``_build_range_terraform_variables``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from shared.range_cells import build_gcp_vm_range_cell_request

from catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)
from cloud.exceptions import CloudProviderNotImplementedError
from config import (
    generate_presigned_url,
    get_range_availability_zone,
    is_gce_range_cell_backend,
    load_aws_polaris_agent_config,
    load_range_network_config,
    resolve_cloud_provider,
    resolve_ngfw_attachment_config,
)
from provisioner_ami import get_ami_id
from provisioner_db_ngfw import get_user_ngfw_data
from state_helpers import _get_cloud_provider

logger = logging.getLogger(__name__)


def _resolve_tf_os_type(role: str, os_type: str) -> str:
    """Map spec role + os_type to the terraform module's os_type enum."""
    if role == "dc" or os_type == "windows":
        resolved = "windows"
    elif role == "attacker" or os_type == "kali":
        resolved = "kali"
    else:
        resolved = "ubuntu"
    return resolved


def _resolve_instance_type(role: str, tf_os_type: str, override: str | None) -> str:
    """Pick the EC2 instance type: per-instance override wins; otherwise role/OS defaults.

    The EC2 instance type is only consumed by the AWS ``aws_instance`` path. GDC
    ranges size VMs from vCPU/memory/disk profiles (``GDC_*_VCPUS`` / ``MEMORY`` /
    ``DISK_SIZE_GIB``) via the VM Runtime asset builder, so the AWS
    ``*_INSTANCE_TYPE`` env vars are intentionally absent on GCP. Don't require
    them there — return the explicit override if any, otherwise an empty string.
    """
    if override:
        return override
    provider = resolve_cloud_provider()
    if provider == "gcp":
        return ""
    if provider == "aws":
        if role == "attacker":
            resolved = _get_kali_instance_type()
        elif role == "dc":
            resolved = _get_dc_instance_type()
        elif tf_os_type == "windows":
            resolved = _get_windows_instance_type()
        else:
            resolved = _get_victim_instance_type()
        return resolved
    raise CloudProviderNotImplementedError(provider)


def _range_egress_mode() -> str:
    """Return the validated AWS runtime egress mode from the task environment."""
    mode = os.environ.get("RANGE_EGRESS_MODE", "allowlist").strip().lower()
    if mode not in {"allowlist", "none"}:
        raise ValueError(f"RANGE_EGRESS_MODE must be 'allowlist' or 'none', got {mode!r}")
    return mode


def _resolve_agent_presigned_url(inst: dict[str, Any]) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
    if _range_egress_mode() == "none":
        return ""
    agent_data = inst.get("agent") or {}
    agent_s3_key = agent_data.get("s3_key")
    if not agent_s3_key:
        return ""
    return generate_presigned_url(
        bucket=os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", ""),
        key=agent_s3_key,
    )


def _resolve_agent_presigned_url_from_inst(inst: dict[str, Any]) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
    return _resolve_agent_presigned_url(inst)


def _build_tf_instance(inst: dict[str, Any]) -> dict[str, Any]:
    """Map one spec instance into the dict shape the terraform module expects."""
    os_type = inst.get("os_type", "ubuntu")
    role = inst.get("role", "victim")
    tf_os_type = _resolve_tf_os_type(role, os_type)
    instance_type = _resolve_instance_type(role, tf_os_type, inst.get("instance_type"))
    ami_key = inst.get("ami_key")
    return {
        "uuid": inst.get("uuid", ""),
        "name": inst.get("name", ""),
        "asset_type": inst.get("asset_type", "vm_runtime_vm"),
        "role": role,
        "os_type": tf_os_type,
        "instance_type": instance_type,
        "agent_presigned_url": _resolve_agent_presigned_url(inst),
        "join_domain": inst.get("join_domain", False),
        "ami_id": get_ami_id(ami_key) if ami_key else "",
    }


def _build_tf_subnets(spec_subnets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate spec subnets+instances into the terraform module's nested format."""
    return [
        {
            "name": subnet.get("name", ""),
            "uuid": subnet.get("uuid", ""),
            # Pre-allocated CIDR.
            "cidr": subnet.get("cidr", ""),
            "connected_to": subnet.get("connected_to", []),
            "instances": [_build_tf_instance(inst) for inst in subnet.get("instances", [])],
        }
        for subnet in spec_subnets
    ]


def _resolve_ngfw_for_range(user_id: int, range_id: int) -> tuple[str, dict[str, Any] | None]:
    """Resolve the user's NGFW attachment for an NGFW-enabled range.

    Returns ``(data_eni_id, attachment_block)``; the attachment block is the
    GCP-specific NGFW config or ``None`` for AWS. Raises ``ValueError`` if the
    user has no provisioned/attachable NGFW.
    """
    ngfw_data = get_user_ngfw_data(user_id)
    if not ngfw_data:
        raise ValueError(
            f"Range requires NGFW (ngfw: true in spec) but user {user_id} has no provisioned NGFW. "
            "User must provision an NGFW before creating NGFW-enabled ranges."
        )
    attachment = resolve_ngfw_attachment_config(ngfw_data)
    if not attachment.is_attachable:
        raise ValueError(
            f"Range requires NGFW but user {user_id}'s NGFW is missing attachable routing state. "
            f"NGFW request_id: {ngfw_data.get('ngfw_request_id')}"
        )
    attachment_block = {
        "cloud_provider": attachment.cloud_provider,
        "management_ip": attachment.management_ip,
        "ssh_key_secret_ref": attachment.ssh_key_secret_ref,
        "dataplane_ip": attachment.dataplane_ip,
        "route_next_hop_ip": attachment.route_next_hop_ip,
        "data_attachment_id": attachment.data_attachment_id,
        "attachment_mode": attachment.attachment_mode,
        "provider_metadata": attachment.provider_metadata,
    }
    logger.info(
        "Using NGFW attachment_mode=%s for range %s",
        attachment.attachment_mode or "unknown",
        range_id,
    )
    return attachment.data_attachment_id, attachment_block


def _build_aws_extra_tf_variables() -> dict[str, Any]:
    """AWS-only Terraform variables: per-OS AMI IDs + instance profile + Secrets Manager CMK."""
    return {
        "kali_ami_id": get_ami_id("kali"),
        "victim_ami_id": get_ami_id("victim"),
        "windows_ami_id": get_ami_id("windows"),
        "dc_ami_id": get_ami_id("dc"),
        "instance_profile_name": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "secrets_kms_key_arn": os.environ["SECRETS_KMS_KEY_ARN"],
        "vpn_edge_subnet_id": os.environ.get("RANGE_VPN_EDGE_SUBNET_ID", ""),
        "vpn_provider_endpoint_security_group_id": os.environ.get("RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID", ""),
        "vpn_gateway_permissions_boundary_arn": os.environ.get("RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN", ""),
    }


def _range_has_polaris_vm_instance(range_spec: dict[str, Any]) -> bool:
    """Return True when the spec has an instance whose ami_key is 'polaris-vm'.

    Captured directly from the raw scenario instance dicts before
    ``_build_tf_instance`` resolves and discards the raw ``ami_key`` string
    (it only keeps the resolved ``ami_id``).
    """
    return any(
        inst.get("ami_key") == "polaris-vm"
        for subnet in range_spec.get("subnets", [])
        for inst in subnet.get("instances", [])
    )


def _get_range_instance_role_arn() -> str:
    """Return the shared range-host IAM role ARN (RANGE_INSTANCE_ROLE_ARN env var).

    Trusted principal for the per-range Polaris Bedrock agent role's
    assume-role policy (#1377).
    """
    return os.environ.get("RANGE_INSTANCE_ROLE_ARN", "").strip()


def _build_aws_polaris_agent_tf_variables(polaris_agent_enabled: bool) -> dict[str, Any]:
    """AWS-only Terraform variables for the per-range Polaris Bedrock agent role (#1377).

    Fails closed: an AWS polaris-vm range with no AWS Polaris agent config, or
    no RANGE_INSTANCE_ROLE_ARN, raises rather than silently disabling the
    per-range agent role -- there is no IMDS/instance-profile fallback.
    """
    if not polaris_agent_enabled:
        return {"polaris_agent_enabled": False}

    agent_config = load_aws_polaris_agent_config()
    if agent_config is None:
        raise RuntimeError(
            "AWS Polaris range requires the AWS Polaris agent Bedrock configuration "
            "(AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN and related AWS_POLARIS_AGENT_* "
            "env vars) to be set; see config.load_aws_polaris_agent_config()."
        )

    range_instance_role_arn = _get_range_instance_role_arn()
    if not range_instance_role_arn:
        raise RuntimeError(
            "AWS Polaris range requires RANGE_INSTANCE_ROLE_ARN (the shared range-host "
            "role ARN) to be set so the per-range Polaris agent role can trust it."
        )

    # Defensive fail-closed guard (ADR-004-R21): config.load_aws_polaris_agent_config()
    # already requires a non-empty boundary for an enabled role, but this seam must
    # never itself emit an enabled-role apply with no permissions boundary, even if a
    # caller builds AWSPolarisAgentConfig directly and bypasses that validation.
    if not agent_config.permissions_boundary_arn:
        raise RuntimeError(
            "AWS Polaris agent config is missing a permissions boundary ARN; an enabled "
            "per-range Bedrock agent role must always carry a permissions boundary "
            "(ADR-004-R21)."
        )

    return {
        "polaris_agent_enabled": True,
        "range_instance_role_arn": range_instance_role_arn,
        "polaris_agent_main_inference_profile_arn": agent_config.main_inference_profile_arn,
        "polaris_agent_small_inference_profile_arn": agent_config.small_inference_profile_arn,
        "polaris_agent_main_backing_model_arns": list(agent_config.main_backing_model_arns),
        "polaris_agent_small_backing_model_arns": list(agent_config.small_backing_model_arns),
        "polaris_agent_permissions_boundary_arn": agent_config.permissions_boundary_arn,
    }


def _build_range_terraform_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
    remote_access_capability: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build Terraform variables dict from range spec and environment."""
    tf_subnets = _build_tf_subnets(range_spec.get("subnets", []))

    ngfw_data_eni_id = ""
    ngfw_attachment: dict[str, Any] | None = None
    if range_spec.get("ngfw", False):
        ngfw_data_eni_id, ngfw_attachment = _resolve_ngfw_for_range(user_id, range_id)

    range_network = load_range_network_config()
    egress_mode = _range_egress_mode()
    variables = {
        "range_id": range_id,
        "user_id": user_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "vpc_id": range_network.network_id,
        "vpc_cidr": range_network.network_cidr,
        "availability_zone": get_range_availability_zone(),
        "s3_endpoint_id": "" if egress_mode == "none" else os.environ.get("S3_ENDPOINT_ID", ""),
        "firewall_endpoint_id": os.environ.get("FIREWALL_ENDPOINT_ID", ""),
        "range_egress_mode": egress_mode,
        "portal_vpc_cidr": range_network.primary_portal_cidr,
        "portal_vpc_peering_id": os.environ.get("PORTAL_VPC_PEERING_ID", ""),
        "ngfw_data_eni_id": ngfw_data_eni_id,
        "subnets": tf_subnets,
    }

    provider = _get_cloud_provider()
    if provider == "gcp":
        if ngfw_attachment:
            variables["ngfw_attachment"] = ngfw_attachment
        return variables

    if provider == "aws":
        if remote_access_capability is not None:
            variables["openvpn_access"] = remote_access_capability
        variables.update(_build_aws_extra_tf_variables())
        variables.update(_build_aws_polaris_agent_tf_variables(_range_has_polaris_vm_instance(range_spec)))
        return variables

    raise CloudProviderNotImplementedError(provider)


def _build_gce_range_cell_variables(
    request_id: str,
    range_id: int,
    range_spec: dict[str, Any],
    scenario_artifact: dict[str, Any] | None,
    remote_access_capability: dict[str, object] | None,
) -> dict[str, Any]:
    """Build the closed GCE VM-cell request around an opaque scenario artifact."""
    if scenario_artifact is None:
        raise RuntimeError("GCP/GCE range cells require a digest-bound scenario artifact")
    bindings = [
        {
            "subnet_ref": subnet.get("uuid", ""),
            "cidr": subnet.get("cidr", ""),
        }
        for subnet in range_spec.get("subnets", [])
        if subnet.get("cidr")
    ]
    payload = scenario_artifact.get("payload", {})
    access_declarations = payload.get("participant_access", []) if isinstance(payload, dict) else []
    return build_gcp_vm_range_cell_request(
        request_id=request_id,
        range_id=range_id,
        scenario_artifact=scenario_artifact,
        network_bindings=bindings,
        access_declarations=access_declarations,
        remote_access=remote_access_capability,
    )


def build_range_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
    *,
    scenario_artifact: dict[str, Any] | None = None,
    backend: str | None = None,
    remote_access_capability: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Return backend-appropriate range variables.

    Routes to the closed GCE range-cell shape when the GCE backend is
    active, otherwise the AWS Terraform variables. This is the single seam the
    range provision/destroy paths call so the GCE backend never receives
    AWS-translated instance shapes.

    ``backend`` is the per-operation ownership binding (#1666). When supplied it
    selects the shape from the persisted binding (so a bound destroy builds the
    right variables even after the deploy selector flips); ``None`` falls back to
    the deploy-wide env selector for the provision path and non-GCP callers.
    """
    use_gce = backend == "gce" if backend else is_gce_range_cell_backend()
    if use_gce:
        return _build_gce_range_cell_variables(
            request_id,
            range_id,
            range_spec,
            scenario_artifact,
            remote_access_capability,
        )
    return _build_range_terraform_variables(
        request_id,
        range_id,
        user_id,
        range_spec,
        remote_access_capability,
    )
