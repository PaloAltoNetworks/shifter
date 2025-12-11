"""
Create Victim Lambda - Launches a victim EC2 instance with XDR agent.

Input: { "range_id": "uuid", "subnet_id": "subnet-xxx" }
Output: { "range_id": "uuid", "victim_instance_id": "i-xxx", "victim_ip": "10.1.X.Y" }
"""

import base64
import logging
import os
import sys

import boto3

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    get_agent_config,
    get_db_connection,
    get_env,
    get_range,
    get_resource_tags,
    update_range,
    validate_env_vars,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "VICTIM_AMI_ID",
    "VICTIM_SECURITY_GROUP_ID",
    "AGENT_S3_BUCKET",
    "DB_HOST",
    "DB_NAME",
]


def validate_s3_path(value: str) -> bool:
    """
    Validate S3 bucket name or key doesn't contain shell injection characters.

    Args:
        value: S3 bucket name or key to validate

    Returns:
        True if safe, False if potentially dangerous
    """
    import re
    # Allow alphanumeric, hyphens, underscores, forward slashes, dots, and equals
    # This covers valid S3 bucket names and common key patterns
    safe_pattern = re.compile(r"^[a-zA-Z0-9._/=-]+$")
    return bool(safe_pattern.match(value))


def get_user_data_script(s3_bucket: str, agent_s3_key: str) -> str:
    """
    Generate user data script to install XDR agent on boot.

    Args:
        s3_bucket: S3 bucket containing agent installers
        agent_s3_key: S3 key for the agent installer

    Returns:
        Base64-encoded user data script

    Raises:
        ValueError: If s3_bucket or agent_s3_key contain unsafe characters
    """
    # Validate inputs to prevent shell injection
    if not validate_s3_path(s3_bucket):
        raise ValueError(f"Invalid S3 bucket name: {s3_bucket}")
    if not validate_s3_path(agent_s3_key):
        raise ValueError(f"Invalid S3 key: {agent_s3_key}")

    script = f"""#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting XDR agent installation..."

# Download agent installer from S3
aws s3 cp 's3://{s3_bucket}/{agent_s3_key}' /tmp/agent-installer

# Make executable and run
chmod +x /tmp/agent-installer
/tmp/agent-installer --install

echo "XDR agent installation complete"
"""
    return base64.b64encode(script.encode()).decode()


def handler(event: dict, context) -> dict:
    """
    Launch a victim EC2 instance in the range subnet.

    1. Read Range from RDS to get subnet_id, agent config
    2. Launch EC2 instance with user data to install XDR agent
    3. Apply security group (SSH from Kali only)
    4. Tag with shifter:range_id, shifter:user_id
    5. Update Range: victim_ip, victim_instance_id
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    logger.info(f"Creating victim instance for range {range_id}")

    # Get configuration from environment
    victim_ami_id = get_env("VICTIM_AMI_ID")
    victim_instance_type = get_env("VICTIM_INSTANCE_TYPE", "t3.micro")
    victim_security_group_id = get_env("VICTIM_SECURITY_GROUP_ID")
    s3_bucket = get_env("AGENT_S3_BUCKET")
    environment = get_env("ENVIRONMENT", "prod")

    # Connect to database
    conn = get_db_connection()
    try:
        # Get range details
        range_data = get_range(conn, range_id)
        if not range_data:
            raise ValueError(f"Range {range_id} not found")

        # Validate range is in provisioning state
        if range_data["status"] != "provisioning":
            raise ValueError(
                f"Range {range_id} is not in provisioning state: {range_data['status']}"
            )

        subnet_id = range_data["subnet_id"]
        if not subnet_id:
            raise ValueError(f"Range {range_id} has no subnet_id - run create_subnet first")

        user_id = range_data["user_id"]
        agent_id = range_data["agent_id"]

        # Check if victim already exists (idempotent)
        if range_data["victim_instance_id"]:
            logger.info(f"Victim already exists: {range_data['victim_instance_id']}")
            return {
                "range_id": range_id,
                "victim_instance_id": range_data["victim_instance_id"],
                "victim_ip": range_data["victim_ip"],
            }

        # Get agent config for S3 key
        agent_config = get_agent_config(conn, agent_id)
        if not agent_config:
            raise ValueError(f"AgentConfig {agent_id} not found")

        agent_s3_key = agent_config["s3_key"]
        logger.info(f"Using agent installer: s3://{s3_bucket}/{agent_s3_key}")

        # Generate user data script
        user_data = get_user_data_script(s3_bucket, agent_s3_key)

        # Create instance
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-victim-{range_id}"})

        response = ec2.run_instances(
            ImageId=victim_ami_id,
            InstanceType=victim_instance_type,
            MinCount=1,
            MaxCount=1,
            SubnetId=subnet_id,
            SecurityGroupIds=[victim_security_group_id],
            UserData=user_data,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": tags,
                }
            ],
            # No IAM role - victim should not have AWS API access
            MetadataOptions={
                "HttpTokens": "required",  # IMDSv2 only
                "HttpPutResponseHopLimit": 1,
            },
        )

        instance = response["Instances"][0]
        instance_id = instance["InstanceId"]
        logger.info(f"Launched instance {instance_id}")

        # Wait for instance to get an IP
        # The private IP is assigned immediately, public IP after launch
        private_ip = instance.get("PrivateIpAddress")

        # If no private IP yet, wait for it
        # Use explicit timeout to stay within Lambda limits (5 sec delay × 50 attempts = 250 sec max)
        if not private_ip:
            waiter = ec2.get_waiter("instance_running")
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 5, "MaxAttempts": 50},
            )

            describe_response = ec2.describe_instances(InstanceIds=[instance_id])
            instance = describe_response["Reservations"][0]["Instances"][0]
            private_ip = instance["PrivateIpAddress"]

        logger.info(f"Instance {instance_id} has IP {private_ip}")

        # Update database
        update_range(
            conn,
            range_id,
            victim_instance_id=instance_id,
            victim_ip=private_ip,
        )
        logger.info(f"Updated range {range_id} with victim info")

        return {
            "range_id": range_id,
            "victim_instance_id": instance_id,
            "victim_ip": private_ip,
        }

    finally:
        conn.close()
