"""Configuration module for Shifter Engine.

This module handles configuration dataclasses, database access,
and utility functions for the provisioner.
"""

import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet

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

    Delegates to the cloud abstraction layer's ObjectStorage implementation.

    This is called during config loading (before provisioning), not during
    resource creation. It's safe because it doesn't create any AWS resources.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        expires_in: URL expiration time in seconds.

    Returns:
        Presigned URL string.
    """
    from cloud import get_object_storage

    storage = get_object_storage()
    return storage.generate_presigned_download_url(bucket=bucket, key=key, expires_in=expires_in)


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
        connected_to: List of subnet names this subnet needs to reach.
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
    # SSM/Bedrock endpoints subnet CIDR for NGFW routing
    ssm_endpoints_subnet_cidr: str = ""


@dataclass(frozen=True)
class RangeNetworkConfig:
    """Provider-neutral network contract for range provisioning.

    This keeps the provisioner's subnet allocation and future Terraform inputs
    behind generic env names while preserving the legacy AWS VPC env vars as
    fallbacks.
    """

    network_id: str
    network_cidr: str
    network_region: str
    portal_network_cidrs: tuple[str, ...] = ()

    @property
    def primary_portal_cidr(self) -> str:
        """Return the first portal CIDR for legacy single-CIDR call sites."""
        return self.portal_network_cidrs[0] if self.portal_network_cidrs else ""


def _parse_csv_env(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def load_range_network_config() -> RangeNetworkConfig:
    """Load the active provider's range-network contract from environment variables."""
    portal_network_cidrs = _parse_csv_env(os.environ.get("PORTAL_NETWORK_CIDRS", ""))
    legacy_portal_cidr = os.environ.get("PORTAL_VPC_CIDR", "")
    if not portal_network_cidrs and legacy_portal_cidr:
        portal_network_cidrs = (legacy_portal_cidr,)

    return RangeNetworkConfig(
        network_id=os.environ.get("RANGE_NETWORK_ID") or os.environ.get("RANGE_VPC_ID", ""),
        network_cidr=os.environ.get("RANGE_NETWORK_CIDR") or os.environ.get("RANGE_VPC_CIDR", ""),
        network_region=(
            os.environ.get("RANGE_NETWORK_REGION")
            or os.environ.get("GCP_REGION")
            or os.environ.get("CLOUD_REGION")
            or os.environ.get("AWS_REGION", "")
        ),
        portal_network_cidrs=portal_network_cidrs,
    )


def get_range_availability_zone(default: str = "us-east-2b") -> str:
    """Return the configured range placement zone for AWS-style callers."""
    return (
        os.environ.get("RANGE_NETWORK_ZONE")
        or os.environ.get("RANGE_AVAILABILITY_ZONE")
        or os.environ.get("AVAILABILITY_ZONE")
        or default
    )


def get_range_from_db(range_id: int) -> dict[str, Any]:
    """Load range configuration from database.

    Returns range data with the new schema where range_config contains
    the full RangeSpec (scenario_id, user_id, subnets with instances).
    Also looks up ngfw_data_eni_id from the user's active NGFW if the
    scenario has ngfw: true.

    Args:
        range_id: Database ID of the range.

    Returns:
        Dict with keys: id, user_id, request_uuid, range_config, ngfw_enabled,
        ngfw_data_eni_id.

    Raises:
        ValueError: If range not found.
    """
    logger.debug("Loading range %d from database", range_id)

    from main import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT
                    r.id,
                    r.user_id,
                    r.uuid,
                    r.range_config
                FROM mission_control_range r
                WHERE r.id = %s
                """,
            (range_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error("Range %d not found in database", range_id)
            raise ValueError(f"Range {range_id} not found")

        user_id = row[1]
        range_config = row[3] or {}

        # Check if scenario requires NGFW (ngfw: true in range_config)
        ngfw_enabled = range_config.get("ngfw", False)

        # Look up data_eni_id and ngfw_instance_id from user's NGFW
        # NGFW can be in any provisioned state - the ENI exists regardless of running state.
        # Include 'stopping' because range provisioner will wait for stop then start the NGFW.
        ngfw_data_eni_id = ""
        ngfw_instance_id = None
        if ngfw_enabled:
            cur.execute(
                """
                SELECT ei.state->>'data_eni_id', ei.id
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status IN ('ready', 'paused', 'pausing', 'resuming')
                  AND ei.state->>'data_eni_id' IS NOT NULL
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row:
                ngfw_data_eni_id = ngfw_row[0] or ""
                ngfw_instance_id = ngfw_row[1]
                logger.debug(
                    "Found ngfw_data_eni_id=%s, ngfw_instance_id=%s for user %d",
                    ngfw_data_eni_id,
                    ngfw_instance_id,
                    user_id,
                )

        result = {
            "id": row[0],
            "user_id": user_id,
            "request_uuid": str(row[2]) if row[2] else "",
            "range_config": range_config,
            "ngfw_enabled": ngfw_enabled,
            "ngfw_data_eni_id": ngfw_data_eni_id,
            "ngfw_instance_id": ngfw_instance_id,
        }

        logger.debug(
            "Loaded range %d: ngfw_enabled=%s, ngfw_data_eni_id=%s",
            range_id,
            result["ngfw_enabled"],
            "present" if result["ngfw_data_eni_id"] else "none",
        )

        return result
