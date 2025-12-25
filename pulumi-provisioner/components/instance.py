"""Instance component for Shifter range provisioning.

This component creates EC2 instances for a range with:
- SSH key generation and storage in Secrets Manager (Pulumi-managed)
- User data scripts for setup
- Proper security group attachment
- DC setup orchestration via SSM Run Command (for DC role)

All AWS resources are created via Pulumi to ensure proper lifecycle management.
"""

import base64
import os
import re
import secrets
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pulumi
import pulumi_aws as aws
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jinja2 import Environment, FileSystemLoader

from .ssm_executor import SSMExecutor
from .setup_orchestrator import SetupOrchestrator, SetupError
from .plans.dc_setup import DCSetupPlan


@dataclass
class DCContext:
    """Context object for DC setup plan.

    Contains all the variables needed by DCSetupPlan.get_context().
    """
    domain_name: str
    netbios_name: str
    dsrm_password: str
    domain_admin_password: str
    hostname: str = ""
    private_ip: str = ""


def validate_s3_path(value: str) -> bool:
    """Validate S3 bucket name or key doesn't contain shell injection characters.

    Args:
        value: S3 bucket name or key to validate.

    Returns:
        True if safe, False if potentially dangerous.
    """
    # Allow alphanumeric, hyphens, underscores, forward slashes, dots, and equals
    # This covers valid S3 bucket names and common key patterns
    safe_pattern = re.compile(r"^[a-zA-Z0-9._/=-]+$")
    return bool(safe_pattern.match(value))


def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH key pair.

    This is a pure Python operation with no AWS calls, safe to run at any time.

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


class InstanceComponent(pulumi.ComponentResource):
    """Creates an EC2 instance for a range.

    All resources (EC2 instance, SSH key secret) are Pulumi-managed for proper
    lifecycle handling. Resources are created on `pulumi up` and destroyed on
    `pulumi destroy`.

    Attributes:
        instance: The created EC2 instance resource.
        instance_id: The instance ID.
        private_ip: The private IP address.
        ssh_key_secret: The Secrets Manager secret resource.
        ssh_key_secret_arn: ARN of the SSH key in Secrets Manager.
        dc_config_param: SSM Parameter for DC config (DC role only, None otherwise).
        dc_config_param_name: SSM Parameter path (DC role only, None otherwise).
        dsrm_password: DSRM password (DC role only, not exported).
    """

    instance: aws.ec2.Instance
    instance_id: pulumi.Output[str]
    private_ip: pulumi.Output[str]
    ssh_key_secret: aws.secretsmanager.Secret
    ssh_key_secret_arn: pulumi.Output[str]
    # DC-specific attributes (None for non-DC instances)
    dc_config_param: Optional[aws.ssm.Parameter]
    dc_config_param_name: Optional[str]
    dsrm_password: Optional[str]  # nosec B105 - generated at runtime, not hardcoded
    domain_admin_password: Optional[str]  # nosec B105 - generated at runtime
    domain_name: Optional[str]
    netbios_name: Optional[str]
    hostname: Optional[str]
    setup_result: Optional[pulumi.Output[bool]]  # Result of DC setup orchestration

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
        agent_presigned_url: str = "",
        dc_config: Optional[dict] = None,
        join_domain: bool = False,
        dc_config_param_name: Optional[str] = None,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Create an EC2 instance for a range.

        Args:
            name: Pulumi resource name prefix.
            range_id: The range ID.
            user_id: The user ID.
            index: Instance index (for multiple instances of same role).
            role: Instance role (attacker/victim/dc).
            os_type: OS type (kali/ubuntu/windows).
            instance_type: EC2 instance type.
            subnet_id: Subnet ID to launch in.
            security_group_id: Security group ID to attach.
            ami_id: AMI ID to use.
            environment: Environment name.
            instance_profile_name: IAM instance profile name (optional).
            agent_s3_bucket: S3 bucket for agent installer (for victims).
            agent_s3_key: S3 key for agent installer (for victims).
            agent_presigned_url: Pre-generated presigned URL for agent (for victims).
            dc_config: DC configuration dict with domain_name and netbios_name (for DC role).
            join_domain: Whether this instance should join a domain (for domain members).
            dc_config_param_name: SSM parameter path for DC config (for domain members).
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:InstanceComponent", name, None, opts)

        # Store role and os_type for output building (avoids closure issues)
        self.role = role
        self.os_type = os_type

        # Common tags for all resources
        common_tags = {
            "shifter:range_id": str(range_id),
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:role": role,
            "shifter:os": os_type,
            "ManagedBy": "pulumi",
        }

        # Generate SSH key pair (pure Python, no AWS calls)
        private_key, public_key = generate_ssh_keypair()

        # Create Secrets Manager secret for SSH private key (Pulumi-managed)
        secret_name_suffix = f"-{index}" if index > 0 else ""
        secret_name = f"shifter/{environment}/range/{range_id}/{role}{secret_name_suffix}-ssh-key"

        self.ssh_key_secret = aws.secretsmanager.Secret(
            f"{name}-ssh-secret",
            name=secret_name,
            description=f"SSH private key for {role} instance in range {range_id}",
            # Force delete without recovery period for range cleanup
            recovery_window_in_days=0,
            tags=common_tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Store the private key in the secret
        ssh_key_version = aws.secretsmanager.SecretVersion(
            f"{name}-ssh-secret-version",
            secret_id=self.ssh_key_secret.id,
            secret_string=private_key,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.ssh_key_secret_arn = self.ssh_key_secret.arn

        # Initialize DC-specific attributes
        self.dc_config_param = None
        self.dc_config_param_name = None
        self.dsrm_password = None
        self.domain_admin_password = None
        self.domain_name = None
        self.netbios_name = None
        self.hostname = None
        self.setup_result = None

        # For DC role, create SSM Parameter and generate passwords
        if role == "dc":
            # Generate passwords
            self.dsrm_password = self._generate_secure_password()
            self.domain_admin_password = self._generate_secure_password()

            # Store DC config for orchestration
            self.domain_name = dc_config.get("domain_name", "internal.shifter") if dc_config else "internal.shifter"
            self.netbios_name = dc_config.get("netbios_name", "SHIFTER") if dc_config else "SHIFTER"
            self.hostname = f"shifter-dc-{range_id}"

            # Create SSM Parameter for DC config (initially empty, orchestration will populate)
            self.dc_config_param_name = f"/shifter/{environment}/range/{range_id}/dc-config"
            self.dc_config_param = aws.ssm.Parameter(
                f"{name}-dc-config",
                name=self.dc_config_param_name,
                type="SecureString",
                value="{}",  # Empty JSON, orchestration will populate after promotion
                description=f"Domain controller configuration for range {range_id}",
                tags=common_tags,
                opts=pulumi.ResourceOptions(parent=self),
            )

        # Generate user data script based on role
        user_data = self._generate_user_data(
            role=role,
            os_type=os_type,
            public_key=public_key,
            range_id=range_id,
            index=index,
            agent_s3_key=agent_s3_key,
            agent_presigned_url=agent_presigned_url,
            dc_config=dc_config,
            join_domain=join_domain,
            member_dc_config_param_name=dc_config_param_name,
        )

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

        # Create instance (depends on secret being created first for proper ordering)
        self.instance = aws.ec2.Instance(
            f"{name}-instance",
            **instance_args,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[ssh_key_version]),
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

    def run_dc_setup(self, region: Optional[str] = None) -> pulumi.Output[bool]:
        """Run DC setup orchestration via SSM Run Command.

        This method should be called after the instance is created to set up
        Active Directory Domain Services. It:
        1. Waits for SSM agent to come online
        2. Installs AD DS feature and reboots
        3. Promotes to Domain Controller and reboots
        4. Verifies AD DS is running

        Args:
            region: AWS region (uses default if not provided)

        Returns:
            pulumi.Output[bool] that resolves to True on success

        Raises:
            SetupError: If any step fails (propagates to Pulumi as stack failure)
        """
        if self.role != "dc":
            # Not a DC instance, return immediately
            return pulumi.Output.from_input(True)

        # Create DC context for the setup plan
        dc_context = DCContext(
            domain_name=self.domain_name,
            netbios_name=self.netbios_name,
            dsrm_password=self.dsrm_password,
            domain_admin_password=self.domain_admin_password,
            hostname=self.hostname,
        )

        def do_setup(instance_id: str) -> bool:
            """Run the DC setup synchronously (called within apply)."""
            pulumi.log.info(f"Starting DC setup for instance {instance_id}")

            # Create executor and orchestrator
            executor = SSMExecutor(region=region)
            orchestrator = SetupOrchestrator(executor=executor)
            plan = DCSetupPlan()

            try:
                # Wait for SSM agent to come online
                pulumi.log.info(f"Waiting for SSM agent on {instance_id}...")
                executor.wait_for_agent(instance_id, timeout_seconds=300)
                pulumi.log.info(f"SSM agent is online on {instance_id}")

                # Get context from plan
                context = plan.get_context(dc_context)

                # Run the orchestration
                pulumi.log.info(f"Running DC setup orchestration on {instance_id}...")
                result = orchestrator.orchestrate(instance_id, plan, context)

                if result.success:
                    pulumi.log.info(f"DC setup completed successfully on {instance_id}")
                    return True
                else:
                    raise SetupError(f"DC setup failed on {instance_id}")

            except Exception as e:
                pulumi.log.error(f"DC setup failed on {instance_id}: {e}")
                raise

        # Use apply to run the setup when instance_id is resolved
        self.setup_result = self.instance_id.apply(do_setup)
        return self.setup_result

    def _generate_user_data(
        self,
        role: str,
        os_type: str,
        public_key: str,
        range_id: int,
        index: int,
        agent_s3_key: str = "",
        agent_presigned_url: str = "",
        dc_config: Optional[dict] = None,
        join_domain: bool = False,
        member_dc_config_param_name: Optional[str] = None,
    ) -> str:
        """Generate user data script for the instance.

        Args:
            role: Instance role.
            os_type: OS type.
            public_key: SSH public key.
            range_id: Range ID.
            index: Instance index.
            agent_s3_key: S3 key for agent installer (for logging).
            agent_presigned_url: Pre-generated presigned URL for agent installer.
            dc_config: DC configuration dict for DC role.
            join_domain: Whether this instance should join a domain.
            member_dc_config_param_name: SSM parameter path for DC config (for domain members).

        Returns:
            Base64-encoded user data script.
        """
        # Load Jinja2 templates
        # Use TEMPLATES_DIR env var if set, otherwise default to relative path
        templates_dir = os.environ.get(
            "TEMPLATES_DIR",
            str(Path(__file__).parent.parent / "templates"),
        )
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        # Validate S3 key if provided (for all victim types)
        if agent_s3_key and not validate_s3_path(agent_s3_key):
            raise ValueError(f"Invalid S3 key (potential shell injection): {agent_s3_key}")

        # Select template based on role and OS
        if role == "attacker":
            template = env.get_template("kali.sh.j2")
            context = {
                "hostname": f"shifter-kali-{range_id}",
                "public_key": public_key,
            }
        elif role == "dc":
            # DC bootstrap only - AD DS setup is handled via SSM orchestration
            template = env.get_template("dc_windows.ps1.j2")
            context = {
                "hostname": f"shifter-dc-{range_id}",
                "public_key": public_key,
            }
        elif os_type == "windows" and join_domain and member_dc_config_param_name:
            # Domain member - Windows instance joining a domain
            template = env.get_template("domain_member_windows.ps1.j2")
            context = {
                "hostname": f"shifter-victim-{range_id}-{index}",
                "public_key": public_key,
                "dc_config_param_name": member_dc_config_param_name,
                "presigned_url": agent_presigned_url,
                "agent_s3_key": agent_s3_key,
            }
        elif os_type == "windows":
            template = env.get_template("victim_windows.ps1.j2")
            context = {
                "hostname": f"shifter-victim-{range_id}-{index}",
                "public_key": public_key,
                "presigned_url": agent_presigned_url,
                "agent_s3_key": agent_s3_key,
            }
        else:
            template = env.get_template("victim_linux.sh.j2")
            context = {
                "hostname": f"shifter-victim-{range_id}-{index}",
                "public_key": public_key,
                "presigned_url": agent_presigned_url,
                "agent_s3_key": agent_s3_key,
            }

        script = template.render(**context)
        return base64.b64encode(script.encode()).decode()

    def _generate_secure_password(self, length: int = 24) -> str:  # nosec B105
        """Generate a cryptographically secure random password for DSRM.

        Args:
            length: Password length (default 24 characters).

        Returns:
            Secure random password meeting Windows complexity requirements.
        """
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        # Generate base password
        password = "".join(secrets.choice(alphabet) for _ in range(length - 4))
        # Ensure complexity: add at least one of each required type
        password += secrets.choice(string.ascii_uppercase)
        password += secrets.choice(string.ascii_lowercase)
        password += secrets.choice(string.digits)
        password += secrets.choice("!@#$%^&*")
        return password

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
