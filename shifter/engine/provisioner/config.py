"""Configuration module for Shifter Engine.

This module handles loading configuration from Pulumi stack config
and environment variables.

Note: Presigned URL generation happens here (before Pulumi runs) because:
1. It's a one-time operation per range, not per-resource
2. It doesn't create AWS resources, just signs a URL
3. The signed URL is passed as data to EC2 user data scripts
"""

import base64
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import boto3
import psycopg
import pulumi
from cryptography.fernet import Fernet

from catalog.instances import (
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

    This is called during config loading (before Pulumi runs), not during
    resource creation. It's safe because it doesn't create any AWS resources.

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
        gwlb_service_name: GWLB VPC Endpoint Service name (from UserNGFW).
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
    kali_security_group_id: str
    victim_security_group_id: str
    instance_profile_name: str
    kali_ami_id: str
    victim_ami_id: str
    windows_ami_id: str
    agent_s3_bucket: str
    availability_zone: str
    gwlb_service_name: str = ""  # GWLB endpoint service name from UserNGFW
    dc_ami_id: str = ""  # AMI ID for DC instances (prebaked with AD DS)
    dc_security_group_id: str = ""  # Security group for Domain Controller instances
    portal_vpc_cidr: str = ""
    portal_vpc_peering_id: str = ""  # VPC peering connection ID for portal route
    # NGFW (VM-Series) configuration
    ngfw_enabled: bool = False
    ngfw_ami_id: str = ""
    ngfw_instance_type: str = "m5.xlarge"
    ngfw_security_group_id: str = ""
    # S3 VPC endpoint for agent downloads (Gateway endpoint ID)
    s3_endpoint_id: str = ""


@dataclass
class NGFWConfig:
    """Configuration for NGFW (UserNGFWStack) provisioning.

    Infrastructure config comes from Pulumi config (set from environment).
    Credential config comes from Pulumi config (set from app_spec in DB).

    Attributes:
        request_id: UUID of the provisioning request (for tagging/correlation).
        instance_uuid: UUID of the NGFW instance (for tagging/DB correlation).
        user_id: Django User ID who owns this NGFW.
        environment: Deployment environment (dev, staging, prod).
        vpc_id: AWS VPC ID for NGFW deployment.
        subnet_id: Subnet ID for NGFW ENIs.
        mgmt_security_group_id: Security group for management ENI.
        data_security_group_id: Security group for data ENI.
        ami_id: VM-Series AMI ID.
        bootstrap_bucket: S3 bucket for bootstrap configuration.
        instance_type: EC2 instance type.
        instance_profile_name: IAM instance profile name.
        scm_pin_id: SCM auto-registration PIN ID.
        scm_pin_value: SCM auto-registration PIN value.
        scm_folder_name: SCM folder name (dgname).
        authcode: VM-Series authcode for licensing.
    """

    request_id: str
    instance_uuid: str  # Required: for tagging and DB correlation
    user_id: int
    environment: str
    # Infrastructure
    vpc_id: str
    subnet_id: str
    mgmt_security_group_id: str
    data_security_group_id: str
    ami_id: str
    bootstrap_bucket: str
    instance_type: str
    instance_profile_name: str
    # Credentials (from app_spec)
    scm_pin_id: str
    scm_pin_value: str
    scm_folder_name: str
    authcode: str


def get_db_connection() -> psycopg.Connection:
    """Get database connection.

    Uses password auth if DB_PASSWORD is set (local dev), otherwise RDS IAM auth.
    """
    db_host = os.environ.get("DB_HOST")
    db_port = int(os.environ.get("DB_PORT", 5432))
    db_user = os.environ.get("DB_USER")
    db_name = os.environ.get("DB_NAME")
    db_password = os.environ.get("DB_PASSWORD")

    # Local dev mode: use password auth
    if db_password:
        if not all([db_host, db_user, db_name]):
            missing = [
                k
                for k, v in [
                    ("DB_HOST", db_host),
                    ("DB_USER", db_user),
                    ("DB_NAME", db_name),
                ]
                if not v
            ]
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        logger.debug("get_db_connection: password auth to %s:%s/%s", db_host, db_port, db_name)
        return psycopg.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )

    # Production mode: use RDS IAM auth
    aws_region = os.environ.get("AWS_REGION")
    if not all([db_host, db_user, db_name, aws_region]):
        missing = [
            k
            for k, v in [
                ("DB_HOST", db_host),
                ("DB_USER", db_user),
                ("DB_NAME", db_name),
                ("AWS_REGION", aws_region),
            ]
            if not v
        ]
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    logger.debug("get_db_connection: RDS IAM auth to %s:%s/%s", db_host, db_port, db_name)
    client = boto3.client("rds")
    token = client.generate_db_auth_token(
        DBHostname=db_host,
        Port=db_port,
        DBUsername=db_user,
        Region=aws_region,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def get_range_from_db(range_id: int) -> dict[str, Any]:
    """Load range configuration from database.

    Returns range data with the new schema where range_config contains
    the full RangeSpec (scenario_id, user_id, subnets with instances).
    Also looks up gwlb_service_name from the linked UserNGFW if present.

    Args:
        range_id: Database ID of the range.

    Returns:
        Dict with keys: id, user_id, request_uuid, range_config, ngfw_enabled,
        gwlb_service_name.

    Raises:
        ValueError: If range not found.
    """
    logger.debug("Loading range %d from database", range_id)

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT
                    r.id,
                    r.user_id,
                    r.uuid,
                    r.range_config,
                    r.gwlb_endpoint_id
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
        gwlb_endpoint_id = row[4] or ""

        # Look up gwlb_service_name from user's active NGFW
        gwlb_service_name = ""
        if gwlb_endpoint_id:
            cur.execute(
                """
                SELECT gwlb_service_name
                FROM mission_control_userngfw
                WHERE user_id = %s
                  AND status IN ('ready', 'active')
                  AND gwlb_service_name != ''
                  AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row:
                gwlb_service_name = ngfw_row[0] or ""
                logger.debug(
                    "Found gwlb_service_name=%s for user %d",
                    gwlb_service_name,
                    user_id,
                )
            else:
                logger.warning(
                    "Range %d has gwlb_endpoint_id but no active NGFW found for user %d",
                    range_id,
                    user_id,
                )

        result = {
            "id": row[0],
            "user_id": user_id,
            "request_uuid": str(row[2]) if row[2] else "",
            "range_config": row[3],  # Full RangeSpec JSON with subnets
            "ngfw_enabled": bool(gwlb_endpoint_id),
            "gwlb_service_name": gwlb_service_name,
        }

        logger.debug(
            "Loaded range %d: ngfw_enabled=%s, gwlb_service_name=%s",
            range_id,
            result["ngfw_enabled"],
            "present" if result["gwlb_service_name"] else "none",
        )

        return result


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


def load_config() -> RangeConfig:
    """Load range configuration from Pulumi config and database.

    Reads range data from database, parses subnets with their instances,
    and loads infrastructure config from Pulumi stack config.

    Returns:
        RangeConfig: Complete configuration for provisioning.

    Raises:
        ValueError: If required configuration is missing.
    """
    logger.info("Loading range configuration")
    config = pulumi.Config()

    # Get range ID from config
    range_id = config.require_int("rangeId")
    environment = config.require("environment")
    logger.debug("Loading range_id=%d, environment=%s", range_id, environment)

    # Load range data from database (includes gwlb_service_name lookup)
    range_data = get_range_from_db(range_id)

    # Extract request_uuid with defensive handling
    request_uuid = str(range_data.get("request_uuid") or "")
    if not request_uuid:
        logger.warning("Range %d has no request_uuid, using empty string", range_id)

    # Get range_config JSON (contains full RangeSpec from CMS)
    range_spec = range_data.get("range_config") or {}
    spec_subnets = range_spec.get("subnets") or []

    if not spec_subnets:
        logger.warning("Range %d has no subnets in range_config", range_id)

    # Get agent bucket for presigned URL generation
    agent_s3_bucket = config.get("agentS3Bucket") or ""

    # Helper to generate presigned URL if we have bucket and key
    def get_presigned_url(s3_key: str | None) -> str | None:
        if agent_s3_bucket and s3_key:
            return generate_presigned_url(agent_s3_bucket, s3_key)
        return None

    # Get instance types from environment (required - no defaults)
    kali_instance_type = os.environ.get("KALI_INSTANCE_TYPE")
    victim_instance_type = os.environ.get("VICTIM_INSTANCE_TYPE")

    if not kali_instance_type or not victim_instance_type:
        raise ValueError("KALI_INSTANCE_TYPE and VICTIM_INSTANCE_TYPE are required")

    # Build subnets with their instances
    subnets = _build_subnet_configs(spec_subnets, get_presigned_url)

    # Extract gwlb_service_name with defensive handling
    gwlb_service_name = str(range_data.get("gwlb_service_name") or "")
    ngfw_enabled = bool(range_data.get("ngfw_enabled", False))

    if ngfw_enabled and not gwlb_service_name:
        logger.warning(
            "Range %d has NGFW enabled but no gwlb_service_name found",
            range_id,
        )

    logger.info(
        "Loaded config: range_id=%d, %d subnets, ngfw=%s",
        range_id,
        len(subnets),
        ngfw_enabled,
    )

    # Get VPC and network configuration from Pulumi config (set via environment)
    return RangeConfig(
        range_id=range_id,
        user_id=int(range_data["user_id"]),
        request_uuid=request_uuid,
        environment=environment,
        subnets=subnets,
        vpc_id=config.require("rangeVpcId"),
        vpc_cidr=config.require("rangeVpcCidr"),
        route_table_id=config.require("rangeRouteTableId"),
        kali_security_group_id=config.require("kaliSecurityGroupId"),
        victim_security_group_id=config.require("victimSecurityGroupId"),
        instance_profile_name=config.get("rangeInstanceProfileName") or "",
        kali_ami_id=config.require("kaliAmiId"),
        victim_ami_id=config.require("victimAmiId"),
        windows_ami_id=config.get("windowsAmiId") or "",
        agent_s3_bucket=config.get("agentS3Bucket") or "",
        availability_zone=config.require("availabilityZone"),
        gwlb_service_name=gwlb_service_name,
        dc_ami_id=config.get("dcAmiId") or "",
        portal_vpc_cidr=config.get("portalVpcCidr") or "",
        portal_vpc_peering_id=config.get("portalVpcPeeringId") or "",
        dc_security_group_id=config.get("dcSecurityGroupId") or "",
        # NGFW (VM-Series) configuration - enabled from DB, config from env vars
        ngfw_enabled=ngfw_enabled,
        ngfw_ami_id=os.environ.get("NGFW_AMI_ID", ""),
        ngfw_instance_type=os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        ngfw_security_group_id=os.environ.get("NGFW_SECURITY_GROUP_ID", ""),
        # S3 VPC endpoint for agent downloads
        s3_endpoint_id=config.get("s3EndpointId") or "",
    )


def load_ngfw_config() -> NGFWConfig:
    """Load NGFW configuration from Pulumi config.

    All values are set by _set_ngfw_stack_config() in main.py before pulumi up.
    Infrastructure values come from environment, credentials from app_spec.

    Returns:
        NGFWConfig: Complete configuration for NGFW provisioning.
    """
    logger.info("Loading NGFW configuration")
    config = pulumi.Config()

    request_id = config.require("requestId")
    instance_uuid = config.require("instanceUuid")
    user_id = config.require_int("userId")

    logger.debug(
        "load_ngfw_config: request_id=%s instance_uuid=%s user_id=%s",
        request_id,
        instance_uuid,
        user_id,
    )

    return NGFWConfig(
        request_id=request_id,
        instance_uuid=instance_uuid,
        user_id=user_id,
        environment=config.require("environment"),
        # Infrastructure
        vpc_id=config.require("ngfwVpcId"),
        subnet_id=config.require("ngfwSubnetId"),
        mgmt_security_group_id=config.require("ngfwMgmtSecurityGroupId"),
        data_security_group_id=config.require("ngfwDataSecurityGroupId"),
        ami_id=config.require("ngfwAmiId"),
        bootstrap_bucket=config.require("bootstrapBucket"),
        instance_type=config.get("ngfwInstanceType") or "m5.xlarge",
        instance_profile_name=config.get("ngfwInstanceProfileName") or "",
        # Credentials (secrets - use require_secret for sensitive values)
        scm_pin_id=config.require("scmPinId"),
        scm_pin_value=config.require("scmPinValue"),
        scm_folder_name=config.require("scmFolderName"),
        authcode=config.require("authcode"),
    )
