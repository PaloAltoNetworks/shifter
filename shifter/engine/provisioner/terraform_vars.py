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

from catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)
from config import (
    generate_presigned_url,
    get_range_availability_zone,
    load_range_network_config,
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
    """Pick the EC2 instance type: per-instance override wins; otherwise role/OS defaults."""
    if override:
        resolved = override
    elif role == "attacker":
        resolved = _get_kali_instance_type()
    elif role == "dc":
        resolved = _get_dc_instance_type()
    elif tf_os_type == "windows":
        resolved = _get_windows_instance_type()
    else:
        resolved = _get_victim_instance_type()
    return resolved


def _resolve_agent_presigned_url(inst: dict[str, Any]) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
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
    }


def _build_range_terraform_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> dict[str, Any]:
    """Build Terraform variables dict from range spec and environment."""
    tf_subnets = _build_tf_subnets(range_spec.get("subnets", []))

    ngfw_data_eni_id = ""
    ngfw_attachment: dict[str, Any] | None = None
    if range_spec.get("ngfw", False):
        ngfw_data_eni_id, ngfw_attachment = _resolve_ngfw_for_range(user_id, range_id)

    range_network = load_range_network_config()
    variables = {
        "range_id": range_id,
        "user_id": user_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "vpc_id": range_network.network_id,
        "vpc_cidr": range_network.network_cidr,
        "availability_zone": get_range_availability_zone(),
        "s3_endpoint_id": os.environ.get("S3_ENDPOINT_ID", ""),
        "firewall_endpoint_id": os.environ.get("FIREWALL_ENDPOINT_ID", ""),
        "portal_vpc_cidr": range_network.primary_portal_cidr,
        "portal_vpc_peering_id": os.environ.get("PORTAL_VPC_PEERING_ID", ""),
        "ngfw_data_eni_id": ngfw_data_eni_id,
        "subnets": tf_subnets,
    }

    if _get_cloud_provider() == "gcp":
        if ngfw_attachment:
            variables["ngfw_attachment"] = ngfw_attachment
        return variables

    variables.update(_build_aws_extra_tf_variables())
    return variables
