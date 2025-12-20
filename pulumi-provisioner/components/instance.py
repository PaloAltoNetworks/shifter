"""Instance component for Shifter range provisioning.

This component creates EC2 instances for a range with:
- SSH key generation and storage in Secrets Manager
- User data scripts for setup
- Proper security group attachment
"""

import base64
import os
from pathlib import Path
from typing import Optional

import boto3
import pulumi
import pulumi_aws as aws
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jinja2 import Environment, FileSystemLoader


def validate_s3_path(value: str) -> bool:
    """Validate S3 bucket name or key doesn't contain shell injection characters.

    Args:
        value: S3 bucket name or key to validate.

    Returns:
        True if safe, False if potentially dangerous.
    """
    import re

    # Allow alphanumeric, hyphens, underscores, forward slashes, dots, and equals
    # This covers valid S3 bucket names and common key patterns
    safe_pattern = re.compile(r"^[a-zA-Z0-9._/=-]+$")
    return bool(safe_pattern.match(value))


def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH key pair.

    Returns:
        tuple: (private_key_pem, public_key_openssh)
    """
    private_key = ed25519.Ed25519PrivateKey.generate()

    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_key_openssh = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode("utf-8")
    )

    return private_key_pem, public_key_openssh


def store_ssh_key(
    private_key: str,
    range_id: int,
    user_id: int,
    role: str,
    environment: str,
) -> str:
    """Store SSH private key in AWS Secrets Manager.

    Args:
        private_key: The SSH private key in PEM format.
        range_id: The range ID.
        user_id: The user ID.
        role: Instance role (attacker/victim).
        environment: Environment name (dev/prod).

    Returns:
        The ARN of the created secret.
    """
    secrets_client = boto3.client("secretsmanager")
    secret_name = f"shifter/{environment}/range/{range_id}/{role}-ssh-key"

    response = secrets_client.create_secret(
        Name=secret_name,
        Description=f"SSH private key for {role} instance in range {range_id}",
        SecretString=private_key,
        Tags=[
            {"Key": "shifter:range_id", "Value": str(range_id)},
            {"Key": "shifter:user_id", "Value": str(user_id)},
            {"Key": "shifter:environment", "Value": environment},
            {"Key": "shifter:resource_type", "Value": f"{role}-ssh-key"},
        ],
    )

    return response["ARN"]


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
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


class InstanceComponent(pulumi.ComponentResource):
    """Creates an EC2 instance for a range.

    Attributes:
        instance: The created EC2 instance resource.
        instance_id: The instance ID.
        private_ip: The private IP address.
        ssh_key_secret_arn: ARN of the SSH key in Secrets Manager.
    """

    instance: aws.ec2.Instance
    instance_id: pulumi.Output[str]
    private_ip: pulumi.Output[str]
    ssh_key_secret_arn: str

    def __init__(
        self,
        name: str,
        range_id: int,
        user_id: int,
        index: int,
        role: str,
        os_type: str,
        instance_type: str,
        subnet_id: pulumi.Input[str],
        security_group_id: str,
        ami_id: str,
        environment: str,
        instance_profile_name: str = "",
        agent_s3_bucket: str = "",
        agent_s3_key: str = "",
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Create an EC2 instance for a range.

        Args:
            name: Pulumi resource name prefix.
            range_id: The range ID.
            user_id: The user ID.
            index: Instance index (for multiple instances of same role).
            role: Instance role (attacker/victim).
            os_type: OS type (kali/ubuntu/windows).
            instance_type: EC2 instance type.
            subnet_id: Subnet ID to launch in.
            security_group_id: Security group ID to attach.
            ami_id: AMI ID to use.
            environment: Environment name.
            instance_profile_name: IAM instance profile name (optional).
            agent_s3_bucket: S3 bucket for agent installer (for victims).
            agent_s3_key: S3 key for agent installer (for victims).
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:InstanceComponent", name, None, opts)

        # Generate SSH key pair
        private_key, public_key = generate_ssh_keypair()

        # Store private key in Secrets Manager
        self.ssh_key_secret_arn = store_ssh_key(
            private_key, range_id, user_id, role, environment
        )

        # Generate user data script based on role
        user_data = self._generate_user_data(
            role=role,
            os_type=os_type,
            public_key=public_key,
            range_id=range_id,
            index=index,
            agent_s3_bucket=agent_s3_bucket,
            agent_s3_key=agent_s3_key,
        )

        # Common tags
        common_tags = {
            "shifter:range_id": str(range_id),
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:role": role,
            "shifter:os": os_type,
            "ManagedBy": "pulumi",
        }

        instance_name = f"shifter-{role}-{range_id}"
        if index > 0:
            instance_name = f"{instance_name}-{index}"

        # Build instance arguments
        instance_args = {
            "ami": ami_id,
            "instance_type": instance_type,
            "subnet_id": subnet_id,
            "vpc_security_group_ids": [security_group_id],
            "user_data_base64": user_data,
            "metadata_options": aws.ec2.InstanceMetadataOptionsArgs(
                http_tokens="required",  # IMDSv2 only
                http_put_response_hop_limit=1,
            ),
            "tags": {
                **common_tags,
                "Name": instance_name,
            },
        }

        # Add instance profile if specified
        if instance_profile_name:
            instance_args["iam_instance_profile"] = instance_profile_name

        # Create instance
        self.instance = aws.ec2.Instance(
            f"{name}-instance",
            **instance_args,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Export outputs
        self.instance_id = self.instance.id
        self.private_ip = self.instance.private_ip

        self.register_outputs(
            {
                "instanceId": self.instance_id,
                "privateIp": self.private_ip,
                "sshKeySecretArn": self.ssh_key_secret_arn,
            }
        )

    def _generate_user_data(
        self,
        role: str,
        os_type: str,
        public_key: str,
        range_id: int,
        index: int,
        agent_s3_bucket: str = "",
        agent_s3_key: str = "",
    ) -> str:
        """Generate user data script for the instance.

        Args:
            role: Instance role.
            os_type: OS type.
            public_key: SSH public key.
            range_id: Range ID.
            index: Instance index.
            agent_s3_bucket: S3 bucket for agent installer.
            agent_s3_key: S3 key for agent installer.

        Returns:
            Base64-encoded user data script.
        """
        # Load Jinja2 templates
        # Use TEMPLATES_DIR env var if set, otherwise default to /app/templates (container)
        # or relative path from this file (local development)
        templates_dir = os.environ.get(
            "TEMPLATES_DIR",
            str(Path(__file__).parent.parent / "templates"),
        )
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        # Select template based on role and OS
        if role == "attacker":
            template = env.get_template("kali.sh.j2")
            context = {
                "hostname": f"shifter-kali-{range_id}",
                "public_key": public_key,
            }
        elif os_type == "windows":
            template = env.get_template("victim_windows.ps1.j2")
            # For Windows, we'd need different handling
            context = {
                "hostname": f"shifter-victim-{range_id}-{index}",
                "public_key": public_key,
            }
        else:
            template = env.get_template("victim_linux.sh.j2")
            # Generate presigned URL for agent installer
            presigned_url = ""
            if agent_s3_bucket and agent_s3_key:
                # Validate S3 key to prevent shell injection
                if not validate_s3_path(agent_s3_key):
                    raise ValueError(f"Invalid S3 key (potential shell injection): {agent_s3_key}")
                presigned_url = generate_presigned_url(agent_s3_bucket, agent_s3_key)

            context = {
                "hostname": f"shifter-victim-{range_id}-{index}",
                "public_key": public_key,
                "presigned_url": presigned_url,
                "agent_s3_key": agent_s3_key,
            }

        script = template.render(**context)
        return base64.b64encode(script.encode()).decode()

    def to_output_dict(self) -> dict:
        """Return instance info as a dictionary for export.

        Returns:
            Dictionary with instance details.
        """
        return {
            "instance_id": self.instance_id,
            "private_ip": self.private_ip,
            "ssh_key_secret_arn": self.ssh_key_secret_arn,
        }
