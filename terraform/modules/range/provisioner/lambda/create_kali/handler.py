"""
Create Kali Lambda - Launches a Kali Linux EC2 instance for attack operations.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "kali_instance_id": "i-xxx", "kali_ip": "10.1.X.Y", "kali_ssh_key_secret_arn": "arn:..." }
"""

import base64
import os
import sys

import boto3
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    ensure_ssh_from_portal,
    get_db_connection,
    get_env,
    get_logger,
    get_range,
    get_resource_tags,
    get_resource_tags_dict,
    update_range,
    validate_env_vars,
)

logger = get_logger(__name__)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "KALI_AMI_ID",
    "KALI_SECURITY_GROUP_ID",
    "DB_HOST",
    "DB_NAME",
]


def generate_ssh_keypair() -> tuple[str, str]:
    """
    Generate an Ed25519 SSH key pair.

    Returns:
        tuple: (private_key_pem, public_key_openssh)
    """
    private_key = ed25519.Ed25519PrivateKey.generate()

    # Private key in PEM format (OpenSSH format)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Public key in OpenSSH format
    public_key_openssh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("utf-8")

    return private_key_pem, public_key_openssh


def store_ssh_key_in_secrets_manager(
    private_key: str, range_id: int, user_id: int, environment: str
) -> str:
    """
    Store SSH private key in AWS Secrets Manager.

    Args:
        private_key: The SSH private key in PEM format
        range_id: The range ID
        user_id: The user ID
        environment: Environment name (dev/prod)

    Returns:
        The ARN of the created secret
    """
    secrets_client = boto3.client("secretsmanager")

    secret_name = f"shifter/{environment}/range/{range_id}/kali-ssh-key"

    # Create the secret with tags for lifecycle management
    response = secrets_client.create_secret(
        Name=secret_name,
        Description=f"SSH private key for Kali instance in range {range_id}",
        SecretString=private_key,
        Tags=[
            {"Key": "shifter:range_id", "Value": str(range_id)},
            {"Key": "shifter:user_id", "Value": str(user_id)},
            {"Key": "shifter:environment", "Value": environment},
            {"Key": "shifter:resource_type", "Value": "kali-ssh-key"},
        ],
    )

    return response["ARN"]


def get_user_data_script(public_key: str, range_id: int) -> str:
    """
    Generate user data script to install kali-linux-headless tools on boot
    and configure SSH access with the provided public key.

    Args:
        public_key: SSH public key in OpenSSH format
        range_id: The range ID (used for hostname)

    Returns:
        Base64-encoded user data script
    """
    # Hostname for XDR console visibility
    hostname = f"shifter-kali-{range_id}"

    script = f"""#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting Kali headless setup..."

# Set hostname for XDR console visibility
echo "Setting hostname to {hostname}..."
hostnamectl set-hostname {hostname}
echo "127.0.0.1 {hostname}" >> /etc/hosts
echo "Hostname set"

# Configure SSH access for MCP server
echo "Configuring SSH access..."
mkdir -p /home/kali/.ssh
chmod 700 /home/kali/.ssh
echo "{public_key}" >> /home/kali/.ssh/authorized_keys
chmod 600 /home/kali/.ssh/authorized_keys
chown -R kali:kali /home/kali/.ssh
echo "SSH access configured"

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
    instance_profile_name = get_env("RANGE_INSTANCE_PROFILE_NAME", "")

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
                "kali_ssh_key_secret_arn": range_data["kali_ssh_key_secret_arn"],
            }

        # Generate SSH key pair for MCP server access
        logger.info("Generating SSH key pair for MCP access")
        private_key, public_key = generate_ssh_keypair()

        # Store private key in Secrets Manager
        logger.info("Storing SSH private key in Secrets Manager")
        ssh_key_secret_arn = store_ssh_key_in_secrets_manager(
            private_key, range_id, user_id, environment
        )
        logger.info(f"SSH key stored: {ssh_key_secret_arn}")

        # Generate user data script with public key
        user_data = get_user_data_script(public_key, range_id)

        # Ensure SSH rule from Portal VPC exists (fixes Terraform drift issue)
        portal_vpc_cidr = get_env("PORTAL_VPC_CIDR", "")
        if portal_vpc_cidr:
            ensure_ssh_from_portal(kali_security_group_id, portal_vpc_cidr)

        # Create instance
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-kali-{range_id}"})

        # Build run_instances parameters
        run_params = {
            "ImageId": kali_ami_id,
            "InstanceType": kali_instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "SubnetId": subnet_id,
            "SecurityGroupIds": [kali_security_group_id],
            "UserData": user_data,
            "TagSpecifications": [
                {
                    "ResourceType": "instance",
                    "Tags": tags,
                }
            ],
            "MetadataOptions": {
                "HttpTokens": "required",  # IMDSv2 only
                "HttpPutResponseHopLimit": 1,
            },
        }

        # Add IAM instance profile if configured (enables SSM access)
        if instance_profile_name:
            run_params["IamInstanceProfile"] = {"Name": instance_profile_name}

        response = ec2.run_instances(**run_params)

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
            kali_ssh_key_secret_arn=ssh_key_secret_arn,
        )
        logger.info(f"Updated range {range_id} with Kali info")

        return {
            "range_id": range_id,
            "kali_instance_id": instance_id,
            "kali_ip": private_ip,
            "kali_ssh_key_secret_arn": ssh_key_secret_arn,
        }

    finally:
        conn.close()
