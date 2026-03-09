"""Configuration module for Shifter Engine.

This module defines dataclasses for range, subnet, and instance configuration,
and provides helpers for presigned URL generation and config building.
"""

import base64
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import boto3
from cryptography.fernet import Fernet

from engine.provisioner.catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)

logger = logging.getLogger(__name__)


def decrypt_field(encrypted_value: str) -> str:
    """Decrypt a Fernet-encrypted field value.

    Used for sensitive fields that are encrypted at rest in the Django
    database using django-encrypted-model-fields.

    Args:
        encrypted_value: Base64-encoded Fernet ciphertext from database

    Returns:
        Decrypted plaintext string

    Raises:
        ValueError: If FIELD_ENCRYPTION_KEY not set or decryption fails
    """
    if not encrypted_value:
        return ""

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        logger.warning("FIELD_ENCRYPTION_KEY not set, returning value as-is")
        return encrypted_value

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
        return fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception as e:
        # If decryption fails, log and return as-is (for backward compatibility)
        logger.warning(f"Failed to decrypt field: {e}")
        return encrypted_value


def generate_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for an S3 object.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        expires_in: URL expiration time in seconds.

    Returns:
        Presigned URL string.
    """
    s3_client = boto3.client("s3")
    url: str = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )
    return url


@dataclass
class InstanceConfig:
    """Configuration for an instance to be provisioned.

    Attributes:
        uuid: Unique identifier from the spec (for tagging and DB correlation).
        name: Display name for UI (e.g., "target-ubuntu", "attacker-kali").
        role: Instance role ("attacker", "victim", or "dc").
        os_type: Operating system type ("kali", "ubuntu", "windows").
        instance_type: AWS instance type (e.g., "t3.medium").
        agent_s3_key: S3 key for agent installer (optional).
        agent_presigned_url: Presigned URL for agent download (optional).
        dc_config: Domain controller configuration (optional).
        join_domain: Whether this instance should join a domain.
        dc_config_param_name: SSM parameter path for DC config (optional).
    """

    uuid: str  # Required: correlation key for tagging and DB updates
    name: str  # Display name like "target-ubuntu" or "attacker-kali"
    role: str  # "attacker", "victim", or "dc"
    os_type: str  # "kali", "ubuntu", "windows"
    instance_type: str
    agent_s3_key: str | None = None  # S3 key for agent installer
    agent_presigned_url: str | None = None  # Presigned URL for agent download
    dc_config: dict[str, str] | None = None  # {"domain_name": "...", "netbios_name": "..."}
    join_domain: bool = False  # Whether this instance should join a domain
    dc_config_param_name: str | None = None  # SSM parameter path for DC config


@dataclass
class SubnetConfig:
    """Configuration for a logical subnet and its instances.

    A logical subnet groups instances that share network visibility.
    Each SubnetConfig becomes one AWS /28 subnet during provisioning.

    Attributes:
        name: Subnet name (e.g., 'attack', 'dc_network').
        uuid: Unique identifier for tagging and correlation.
        instances: List of instances in this subnet.
        connected_to: List of subnet names this subnet can reach (bidirectional).
    """

    name: str
    uuid: str
    instances: list[InstanceConfig]
    connected_to: list[str] = field(default_factory=list)


@dataclass
class RangeConfig:
    """Configuration for a complete range.

    Attributes:
        range_id: Database ID for the range.
        user_id: Owner's user ID.
        request_uuid: Correlation key for the provisioning request.
        environment: Deployment environment (dev, staging, prod).
        subnets: List of logical subnets with their instances.
        vpc_id: AWS VPC ID for range deployment.
        vpc_cidr: VPC CIDR block (e.g., '10.1.0.0/16').
        ngfw_data_eni_id: NGFW data ENI ID for inter-subnet routing.
            Empty string if no NGFW attached to this range.
    """

    range_id: int
    user_id: int
    request_uuid: str
    environment: str
    subnets: list[SubnetConfig]
    vpc_id: str
    vpc_cidr: str
    route_table_id: str
    instance_profile_name: str
    kali_ami_id: str
    victim_ami_id: str
    windows_ami_id: str
    agent_s3_bucket: str
    availability_zone: str
    ngfw_data_eni_id: str = ""  # NGFW data ENI ID for inter-subnet routing
    dc_ami_id: str = ""  # AMI ID for DC instances (prebaked with AD DS)
    portal_vpc_cidr: str = ""
    portal_vpc_peering_id: str = ""  # VPC peering connection ID for portal route
    # NGFW (VM-Series) configuration
    ngfw_enabled: bool = False
    ngfw_ami_id: str = ""
    ngfw_instance_type: str = "m5.xlarge"
    # NGFW connection info for subnet configuration (set when ngfw_enabled=True)
    ngfw_management_ip: str = ""  # NGFW management IP for SSH
    ngfw_ssh_key_secret_arn: str = ""  # Secrets Manager ARN for SSH private key
    ngfw_subnet_cidr: str = ""  # NGFW subnet CIDR for computing gateway IP
    # S3 VPC endpoint for agent downloads (Gateway endpoint ID)
    s3_endpoint_id: str = ""
    # AWS Network Firewall endpoint ID for internet egress from range subnets
    firewall_endpoint_id: str = ""


def _build_instance_config(
    inst: dict[str, Any],
    get_presigned_url: Callable[[str | None], str | None],
    subnet_name: str,
) -> InstanceConfig:
    """Build InstanceConfig from raw instance dict.

    Args:
        inst: Instance dict from range_config.
        get_presigned_url: Function to generate presigned URLs.
        subnet_name: Name of the parent subnet (for error context).

    Returns:
        Configured InstanceConfig.

    Raises:
        ValueError: If instance is missing required 'uuid' field.
    """
    # Extract and validate uuid (required for tagging and DB correlation)
    instance_uuid = inst.get("uuid")
    if not instance_uuid:
        role = inst.get("role", "unknown")
        raise ValueError(f"Instance (role={role}) in subnet '{subnet_name}' missing required 'uuid' field")
    instance_uuid = str(instance_uuid)

    role = inst.get("role", "victim")
    os_type = inst.get("os_type", "ubuntu")

    # Build display name: use "target" instead of "victim" for user-facing labels
    display_role = "target" if role == "victim" else role
    instance_name = inst.get("name") or f"{display_role}-{os_type}"
    # Ensure any existing "victim" in name is replaced with "target"
    instance_name = instance_name.replace("victim", "target")

    # Get instance_type from catalog defaults based on role/os
    if role == "attacker":
        instance_type = _get_kali_instance_type()
    elif role == "dc":
        instance_type = _get_dc_instance_type()
    elif os_type == "windows":
        instance_type = _get_windows_instance_type()
    else:
        instance_type = _get_victim_instance_type()

    # Get agent s3_key from instance's agent details
    agent_data = inst.get("agent") or {}
    agent_s3_key = agent_data.get("s3_key")

    # Extract dc_config ensuring proper type
    raw_dc_config = inst.get("dc_config")
    dc_config: dict[str, str] | None = None
    if raw_dc_config and isinstance(raw_dc_config, dict):
        dc_config = {
            "domain_name": str(raw_dc_config.get("domain_name", "")),
            "netbios_name": str(raw_dc_config.get("netbios_name", "")),
        }

    return InstanceConfig(
        uuid=instance_uuid,
        name=instance_name,
        role=role,
        os_type=os_type,
        instance_type=instance_type,
        agent_s3_key=agent_s3_key,
        agent_presigned_url=get_presigned_url(agent_s3_key),
        dc_config=dc_config,
        join_domain=bool(inst.get("join_domain", False)),
    )


def _build_subnet_configs(
    spec_subnets: list[dict[str, Any]],
    get_presigned_url: Callable[[str | None], str | None],
) -> list[SubnetConfig]:
    """Build SubnetConfig list from range_config.subnets.

    Args:
        spec_subnets: List of subnet dicts from range_config.
        get_presigned_url: Function to generate presigned URLs.

    Returns:
        List of SubnetConfig objects.

    Raises:
        ValueError: If subnet is missing required fields.
    """
    subnets: list[SubnetConfig] = []

    for subnet_dict in spec_subnets:
        subnet_name = subnet_dict.get("name")
        subnet_uuid = subnet_dict.get("uuid")

        # Defensive: validate required fields
        if not subnet_name:
            raise ValueError("Subnet missing required 'name' field")
        if not subnet_uuid:
            raise ValueError(f"Subnet '{subnet_name}' missing required 'uuid' field")

        # Build instances for this subnet
        instances: list[InstanceConfig] = []
        raw_instances = subnet_dict.get("instances") or []

        if not raw_instances:
            logger.warning("Subnet '%s' has no instances", subnet_name)

        for inst in raw_instances:
            instances.append(_build_instance_config(inst, get_presigned_url, subnet_name))

        # Get connected_to, ensuring it's a list of strings
        connected_to_raw = subnet_dict.get("connected_to") or []
        connected_to = [str(name) for name in connected_to_raw if name]

        subnets.append(
            SubnetConfig(
                name=str(subnet_name),
                uuid=str(subnet_uuid),
                instances=instances,
                connected_to=connected_to,
            )
        )

        logger.debug(
            "Built subnet '%s' with %d instances, connected_to=%s",
            subnet_name,
            len(instances),
            connected_to,
        )

    return subnets
