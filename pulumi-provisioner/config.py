"""Configuration module for Pulumi provisioner.

This module handles loading configuration from Pulumi stack config
and environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional

import boto3
import psycopg
import pulumi


@dataclass
class InstanceConfig:
    """Configuration for an instance to be provisioned."""

    role: str  # "attacker" or "victim"
    os_type: str  # "kali", "ubuntu", "windows"
    instance_type: str
    agent_id: Optional[int] = None  # Agent config ID for victim instances
    agent_s3_key: Optional[str] = None  # S3 key for agent installer


@dataclass
class RangeConfig:
    """Configuration for a complete range."""

    range_id: int
    user_id: int
    subnet_index: int
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
    portal_vpc_cidr: str = ""


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
    """Load range configuration from database."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.user_id,
                    r.subnet_index,
                    r.agent_id,
                    r.instance_config,
                    a.s3_key as agent_s3_key
                FROM mission_control_range r
                LEFT JOIN mission_control_agentconfig a ON r.agent_id = a.id
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
                "subnet_index": row[2],
                "agent_id": row[3],
                "instance_config": row[4],
                "agent_s3_key": row[5],
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

    # Parse instance_config from database or use defaults
    db_instance_config = range_data.get("instance_config") or []

    # If no custom config, use default (1 Kali + 1 Victim)
    if not db_instance_config:
        instances = [
            InstanceConfig(
                role="attacker",
                os_type="kali",
                instance_type="t3.small",
            ),
            InstanceConfig(
                role="victim",
                os_type="ubuntu",
                instance_type="t3.micro",
                agent_id=range_data.get("agent_id"),
                agent_s3_key=range_data.get("agent_s3_key"),
            ),
        ]
    else:
        # Parse custom instance configs
        instances = []
        for inst in db_instance_config:
            instances.append(
                InstanceConfig(
                    role=inst.get("role", "victim"),
                    os_type=inst.get("os", "ubuntu"),
                    instance_type=inst.get("instance_type", "t3.micro"),
                    agent_id=inst.get("agent_id"),
                    agent_s3_key=inst.get("agent_s3_key"),
                )
            )

    # Get VPC and network configuration from Pulumi config (set via environment)
    return RangeConfig(
        range_id=range_id,
        user_id=range_data["user_id"],
        subnet_index=range_data["subnet_index"],
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
        portal_vpc_cidr=config.get("portalVpcCidr") or "",
    )
