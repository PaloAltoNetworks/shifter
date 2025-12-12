"""
Create Kali Lambda - Launches a Kali Linux EC2 instance for attack operations.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "kali_instance_id": "i-xxx", "kali_ip": "10.1.X.Y" }
"""

import base64
import logging
import os
import sys

import boto3

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
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
    "KALI_AMI_ID",
    "KALI_SECURITY_GROUP_ID",
    "DB_HOST",
    "DB_NAME",
]


def get_user_data_script() -> str:
    """
    Generate user data script to install kali-linux-headless tools on boot.

    Returns:
        Base64-encoded user data script
    """
    script = """#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting Kali headless setup..."

# Update package lists
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# Install kali-linux-headless metapackage (core pentesting tools)
apt-get install -y kali-linux-headless

echo "Kali headless setup complete"
"""
    return base64.b64encode(script.encode()).decode()


def handler(event: dict, context) -> dict:
    """
    Launch a Kali Linux EC2 instance in the range subnet.

    1. Read Range from RDS to get subnet_id
    2. Launch EC2 instance with user data to install headless tools
    3. Apply security group (SSH access for MCP)
    4. Tag with shifter:range_id, shifter:user_id
    5. Update Range: kali_ip, kali_instance_id
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    logger.info(f"Creating Kali instance for range {range_id}")

    # Get configuration from environment
    kali_ami_id = get_env("KALI_AMI_ID")
    kali_instance_type = get_env("KALI_INSTANCE_TYPE", "t3.small")
    kali_security_group_id = get_env("KALI_SECURITY_GROUP_ID")
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

        # Check if Kali already exists (idempotent)
        if range_data["kali_instance_id"]:
            logger.info(f"Kali already exists: {range_data['kali_instance_id']}")
            return {
                "range_id": range_id,
                "kali_instance_id": range_data["kali_instance_id"],
                "kali_ip": range_data["kali_ip"],
            }

        # Generate user data script
        user_data = get_user_data_script()

        # Create instance
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-kali-{range_id}"})

        response = ec2.run_instances(
            ImageId=kali_ami_id,
            InstanceType=kali_instance_type,
            MinCount=1,
            MaxCount=1,
            SubnetId=subnet_id,
            SecurityGroupIds=[kali_security_group_id],
            UserData=user_data,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": tags,
                }
            ],
            # No IAM role - Kali should not have AWS API access
            MetadataOptions={
                "HttpTokens": "required",  # IMDSv2 only
                "HttpPutResponseHopLimit": 1,
            },
        )

        instance = response["Instances"][0]
        instance_id = instance["InstanceId"]
        logger.info(f"Launched Kali instance {instance_id}")

        # Wait for instance to get an IP
        # The private IP is assigned immediately, public IP after launch
        private_ip = instance.get("PrivateIpAddress")

        # If no private IP yet, wait for it
        # Use explicit timeout to stay within Lambda limits (5 sec delay x 50 attempts = 250 sec max)
        if not private_ip:
            waiter = ec2.get_waiter("instance_running")
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 5, "MaxAttempts": 50},
            )

            describe_response = ec2.describe_instances(InstanceIds=[instance_id])
            instance = describe_response["Reservations"][0]["Instances"][0]
            private_ip = instance["PrivateIpAddress"]

        logger.info(f"Kali instance {instance_id} has IP {private_ip}")

        # Update database
        update_range(
            conn,
            range_id,
            kali_instance_id=instance_id,
            kali_ip=private_ip,
        )
        logger.info(f"Updated range {range_id} with Kali info")

        return {
            "range_id": range_id,
            "kali_instance_id": instance_id,
            "kali_ip": private_ip,
        }

    finally:
        conn.close()
