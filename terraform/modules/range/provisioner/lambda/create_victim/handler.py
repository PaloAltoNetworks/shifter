"""
Create Victim Lambda - Launches a victim EC2 instance with XDR agent.

Input: { "range_id": "uuid", "subnet_id": "subnet-xxx" }
Output: { "range_id": "uuid", "victim_instance_id": "i-xxx", "victim_ip": "10.1.X.Y", "victim_ssh_key_secret_arn": "arn:..." }
"""

import base64
import logging
import os
import sys

import boto3
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

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


def generate_ssh_keypair() -> tuple[str, str]:
    """
    Generate an Ed25519 SSH key pair for MCP server access.

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

    secret_name = f"shifter/{environment}/range/{range_id}/victim-ssh-key"

    # Create the secret with tags for lifecycle management
    response = secrets_client.create_secret(
        Name=secret_name,
        Description=f"SSH private key for Victim instance in range {range_id}",
        SecretString=private_key,
        Tags=[
            {"Key": "shifter:range_id", "Value": str(range_id)},
            {"Key": "shifter:user_id", "Value": str(user_id)},
            {"Key": "shifter:environment", "Value": environment},
            {"Key": "shifter:resource_type", "Value": "victim-ssh-key"},
        ],
    )

    return response["ARN"]


def get_user_data_script(
    presigned_url: str, agent_s3_key: str, public_key: str
) -> str:
    """
    Generate user data script to install XDR agent on boot and configure SSH access.

    Supports multiple installer formats:
    - .sh: Shell scripts (executed directly)
    - .deb: Debian packages (installed via dpkg)
    - .rpm: RPM packages (installed via rpm)
    - .tar.gz/.tgz: Tarballs (extracted and first .sh file executed)
    - .zip: Archives (extracted and first .sh file executed)
    - Binary executables (executed with --install flag)

    Args:
        presigned_url: Pre-signed S3 URL for downloading the agent installer
        agent_s3_key: S3 key for the agent installer (used to detect file type)
        public_key: SSH public key in OpenSSH format for MCP access

    Returns:
        Base64-encoded user data script

    Raises:
        ValueError: If agent_s3_key contains unsafe characters
    """
    # Validate inputs to prevent shell injection
    if not validate_s3_path(agent_s3_key):
        raise ValueError(f"Invalid S3 key: {agent_s3_key}")

    script = f"""#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting victim instance setup..."

# Configure SSH access for MCP server
echo "Configuring SSH access..."
mkdir -p /home/ubuntu/.ssh
chmod 700 /home/ubuntu/.ssh
echo "{public_key}" >> /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
chown -R ubuntu:ubuntu /home/ubuntu/.ssh
echo "SSH access configured"

# Download agent installer using presigned URL (no AWS CLI needed)
echo "Downloading XDR agent installer..."
INSTALLER_KEY="{agent_s3_key}"
INSTALLER_FILE="/tmp/agent-installer"
curl -sSf -o "$INSTALLER_FILE" '{presigned_url}'

# Detect file type and install accordingly
echo "Detecting installer type..."

# Helper to deploy cortex.conf before running installer
deploy_cortex_conf() {{
    local extract_dir="$1"
    local conf_file=""

    # Find cortex.conf in extracted directory
    conf_file=$(find "$extract_dir" -name "cortex.conf" -type f | head -1)

    if [ -n "$conf_file" ]; then
        echo "Found cortex.conf: $conf_file"
        mkdir -p /etc/panw
        cp "$conf_file" /etc/panw/cortex.conf
        chmod 644 /etc/panw/cortex.conf
        echo "Deployed cortex.conf to /etc/panw/"
        return 0
    fi

    echo "WARNING: No cortex.conf found in archive"
    return 1
}}

# Helper to find and run any .sh file in extracted directory
run_extracted_installer() {{
    local extract_dir="$1"
    local script=""

    # IMPORTANT: Deploy cortex.conf BEFORE running installer (required by Cortex XDR)
    deploy_cortex_conf "$extract_dir"

    # Find first .sh file (check root first, then subdirs)
    script=$(find "$extract_dir" -maxdepth 1 -name "*.sh" -type f | head -1)
    if [ -z "$script" ]; then
        script=$(find "$extract_dir" -maxdepth 2 -name "*.sh" -type f | head -1)
    fi

    if [ -n "$script" ]; then
        echo "Found installer script: $script"
        chmod +x "$script"
        # Run as root (user-data runs as root, but be explicit)
        "$script"
        return 0
    fi

    echo "ERROR: No .sh installer found in archive"
    echo "Contents:"
    find "$extract_dir" -type f
    return 1
}}

install_agent() {{
    local file="$1"
    local filename=$(basename "$INSTALLER_KEY")

    # First, try to detect by file extension
    case "$filename" in
        *.sh)
            echo "Installing via shell script..."
            chmod +x "$file"
            "$file"
            return
            ;;
        *.deb)
            echo "Installing via dpkg..."
            dpkg -i "$file" || apt-get install -f -y
            return
            ;;
        *.rpm)
            echo "Installing via rpm..."
            rpm -i "$file" || yum install -y "$file"
            return
            ;;
        *.tar.gz|*.tgz)
            echo "Extracting tarball..."
            mkdir -p /tmp/agent-extract
            tar xzf "$file" -C /tmp/agent-extract
            run_extracted_installer /tmp/agent-extract
            return
            ;;
        *.zip)
            echo "Extracting zip archive..."
            mkdir -p /tmp/agent-extract
            unzip -o "$file" -d /tmp/agent-extract
            run_extracted_installer /tmp/agent-extract
            return
            ;;
    esac

    # Fall back to MIME type detection
    local mime_type=$(file -b --mime-type "$file")
    echo "Detected MIME type: $mime_type"

    case "$mime_type" in
        application/x-debian-package|application/vnd.debian.binary-package)
            echo "Installing via dpkg..."
            dpkg -i "$file" || apt-get install -f -y
            ;;
        application/x-rpm)
            echo "Installing via rpm..."
            rpm -i "$file" || yum install -y "$file"
            ;;
        text/x-shellscript|application/x-shellscript|application/x-sh)
            echo "Installing via shell script..."
            chmod +x "$file"
            "$file"
            ;;
        application/gzip|application/x-gzip)
            echo "Extracting gzip archive..."
            mkdir -p /tmp/agent-extract
            tar xzf "$file" -C /tmp/agent-extract
            run_extracted_installer /tmp/agent-extract
            ;;
        application/zip)
            echo "Extracting zip archive..."
            mkdir -p /tmp/agent-extract
            unzip -o "$file" -d /tmp/agent-extract
            run_extracted_installer /tmp/agent-extract
            ;;
        application/x-executable|application/octet-stream)
            echo "Installing via executable..."
            chmod +x "$file"
            "$file" --install || "$file"
            ;;
        *)
            echo "Unknown installer type: $mime_type"
            echo "Attempting to run as executable..."
            chmod +x "$file"
            "$file" --install || "$file"
            ;;
    esac
}}

echo "Installing XDR agent..."
install_agent "$INSTALLER_FILE"

echo "Victim instance setup complete"
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
        agent_id = range_data["agent_id"]

        # Check if victim already exists (idempotent)
        if range_data["victim_instance_id"]:
            logger.info(f"Victim already exists: {range_data['victim_instance_id']}")
            return {
                "range_id": range_id,
                "victim_instance_id": range_data["victim_instance_id"],
                "victim_ip": range_data["victim_ip"],
                "victim_ssh_key_secret_arn": range_data["victim_ssh_key_secret_arn"],
            }

        # Get agent config for S3 key
        agent_config = get_agent_config(conn, agent_id)
        if not agent_config:
            raise ValueError(f"AgentConfig {agent_id} not found")

        agent_s3_key = agent_config["s3_key"]
        logger.info(f"Using agent installer: s3://{s3_bucket}/{agent_s3_key}")

        # Generate SSH key pair for MCP server access
        logger.info("Generating SSH key pair for MCP access")
        private_key, public_key = generate_ssh_keypair()

        # Store private key in Secrets Manager
        logger.info("Storing SSH private key in Secrets Manager")
        ssh_key_secret_arn = store_ssh_key_in_secrets_manager(
            private_key, range_id, user_id, environment
        )
        logger.info(f"SSH key stored: {ssh_key_secret_arn}")

        # Generate presigned URL for agent installer (valid for 1 hour)
        s3_client = boto3.client("s3")
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": s3_bucket, "Key": agent_s3_key},
            ExpiresIn=3600,
        )
        logger.info("Generated presigned URL for agent installer")

        # Generate user data script with presigned URL
        user_data = get_user_data_script(presigned_url, agent_s3_key, public_key)

        # Create instance
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-victim-{range_id}"})

        # Build run_instances parameters
        run_params = {
            "ImageId": victim_ami_id,
            "InstanceType": victim_instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "SubnetId": subnet_id,
            "SecurityGroupIds": [victim_security_group_id],
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
            victim_ssh_key_secret_arn=ssh_key_secret_arn,
        )
        logger.info(f"Updated range {range_id} with victim info")

        return {
            "range_id": range_id,
            "victim_instance_id": instance_id,
            "victim_ip": private_ip,
            "victim_ssh_key_secret_arn": ssh_key_secret_arn,
        }

    finally:
        conn.close()
