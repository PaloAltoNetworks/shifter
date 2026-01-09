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
from dataclasses import dataclass

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
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


@dataclass
class InstanceConfig:
    """Configuration for an instance to be provisioned."""

    role: str  # "attacker", "victim", or "dc"
    os_type: str  # "kali", "ubuntu", "windows"
    instance_type: str
    agent_s3_key: str | None = None  # S3 key for agent installer
    agent_presigned_url: str | None = None  # Presigned URL for agent download
    dc_config: dict | None = None  # {"domain_name": "...", "netbios_name": "..."}
    join_domain: bool = False  # Whether this instance should join a domain
    dc_config_param_name: str | None = None  # SSM parameter path for DC config


@dataclass
class RangeConfig:
    """Configuration for a complete range."""

    range_id: int
    user_id: int
    environment: str
    instances: list[InstanceConfig]
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
    dc_ami_id: str = ""  # AMI ID for DC instances (prebaked with AD DS)
    dc_security_group_id: str = ""  # Security group for Domain Controller instances
    portal_vpc_cidr: str = ""
    # NGFW (VM-Series) configuration
    ngfw_enabled: bool = False
    ngfw_ami_id: str = ""
    ngfw_instance_type: str = "m5.xlarge"
    ngfw_security_group_id: str = ""


@dataclass
class NGFWConfig:
    """Configuration for NGFW (UserNGFWStack) provisioning.

    Infrastructure config comes from Pulumi config (set from environment).
    Credential config comes from Pulumi config (set from app_spec in DB).
    """

    request_id: str
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
    """Get database connection using RDS IAM auth."""
    client = boto3.client("rds")
    token = client.generate_db_auth_token(
        DBHostname=os.environ["DB_HOST"],
        Port=int(os.environ.get("DB_PORT", 5432)),
        DBUsername=os.environ["DB_USER"],
        Region=os.environ["AWS_REGION"],
    )
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=token,
        sslmode="require",
    )


def get_range_from_db(range_id: int) -> dict:
    """Load range configuration from database.

    Returns range data with the new schema where range_config contains
    the full RangeSpec (scenario_id, user_id, instances with agent details).
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT
                    r.id,
                    r.user_id,
                    r.range_config,
                    r.ngfw_id IS NOT NULL as ngfw_enabled
                FROM mission_control_range r
                WHERE r.id = %s
                """,
            (range_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range {range_id} not found")

        return {
            "id": row[0],
            "user_id": row[1],
            "range_config": row[2],  # Full RangeSpec JSON
            "ngfw_enabled": row[3],
        }


def load_config() -> RangeConfig:
    """Load range configuration from Pulumi config and database.

    Returns:
        RangeConfig: Complete configuration for provisioning.
    """
    config = pulumi.Config()

    # Get range ID from config
    range_id = config.require_int("rangeId")
    environment = config.require("environment")

    # Load range data from database
    range_data = get_range_from_db(range_id)

    # Get range_config JSON (contains full RangeSpec from CMS)
    range_spec = range_data.get("range_config") or {}
    spec_instances = range_spec.get("instances") or []

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

    # Build instances from range_config.instances (new schema)
    instances = []
    for inst in spec_instances:
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

        # Get agent s3_key from instance's agent details (new schema)
        agent_data = inst.get("agent") or {}
        agent_s3_key = agent_data.get("s3_key")

        instances.append(
            InstanceConfig(
                role=role,
                os_type=os_type,
                instance_type=instance_type,
                agent_s3_key=agent_s3_key,
                agent_presigned_url=get_presigned_url(agent_s3_key),
                dc_config=inst.get("dc_config"),
                join_domain=inst.get("join_domain", False),
            )
        )

    # Get VPC and network configuration from Pulumi config (set via environment)
    return RangeConfig(
        range_id=range_id,
        user_id=range_data["user_id"],
        environment=environment,
        instances=instances,
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
        dc_ami_id=config.get("dcAmiId") or "",
        portal_vpc_cidr=config.get("portalVpcCidr") or "",
        dc_security_group_id=config.get("dcSecurityGroupId") or "",
        # NGFW (VM-Series) configuration - enabled from DB, config from env vars
        ngfw_enabled=range_data.get("ngfw_enabled", False),
        ngfw_ami_id=os.environ.get("NGFW_AMI_ID", ""),
        ngfw_instance_type=os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        ngfw_security_group_id=os.environ.get("NGFW_SECURITY_GROUP_ID", ""),
    )


def load_ngfw_config() -> NGFWConfig:
    """Load NGFW configuration from Pulumi config.

    All values are set by _set_ngfw_stack_config() in main.py before pulumi up.
    Infrastructure values come from environment, credentials from app_spec.

    Returns:
        NGFWConfig: Complete configuration for NGFW provisioning.
    """
    config = pulumi.Config()

    return NGFWConfig(
        request_id=config.require("requestId"),
        user_id=config.require_int("userId"),
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
