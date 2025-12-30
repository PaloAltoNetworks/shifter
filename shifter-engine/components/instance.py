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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import pulumi
import pulumi_aws as aws
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jinja2 import Environment, FileSystemLoader

from .ssm_executor import SSMExecutor
from .setup_orchestrator import SetupOrchestrator, SetupError
from .plans.domain_join import DomainJoinPlan
from .plans.xdr_agent_install import XDRAgentInstallPlan
from .plans.bootstrap import BootstrapPlan
from .plans.linux_bootstrap import LinuxBootstrapPlan
from .plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan


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
    public_key: Optional[str]  # Stored for SSM orchestration
    agent_presigned_url: Optional[str]  # For XDR agent installation on DC
    ssh_user: Optional[str]  # SSH user for Linux instances (kali, ubuntu, ec2-user)
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
        self.public_key = None
        self.agent_presigned_url = None
        self.ssh_user = None
        self.setup_result = None
        self.join_domain = join_domain  # Store for run_setup() domain join logic

        # Store attributes for all instance types (needed for run_setup)
        # Generate hostname based on role (same logic as _generate_user_data)
        if role == "attacker":
            self.hostname = f"shifter-kali-{range_id}"
            self.public_key = public_key
            self.ssh_user = "kali"
        elif role == "victim":
            self.hostname = f"shifter-victim-{range_id}-{index}"
            self.public_key = public_key
            self.agent_presigned_url = agent_presigned_url if agent_presigned_url else None
            # Determine SSH user based on OS type
            if os_type == "kali":
                self.ssh_user = "kali"
            elif os_type in ("ubuntu", "amazon-linux"):
                self.ssh_user = "ubuntu" if os_type == "ubuntu" else "ec2-user"
            # Windows doesn't use SSH user (uses WinRM/RDP)

        # For DC role, read config from environment variables (prebaked AMI)
        if role == "dc":
            # Read from environment variables (set by Terraform via ECS task definition)
            self.domain_name = os.environ.get("DC_DOMAIN_NAME", "internal.shifter")
            self.domain_admin_password = os.environ.get("DC_DOMAIN_PASSWORD", "")

            if not self.domain_admin_password:
                raise ValueError("DC_DOMAIN_PASSWORD environment variable is required for DC instances")

            # Prebaked AMI has fixed hostname DC01 and no DSRM password needed
            self.dsrm_password = None  # Not used with prebaked AMI
            self.netbios_name = dc_config.get("netbios_name", "INTSHIFTER") if dc_config else "INTSHIFTER"
            self.hostname = "DC01"  # Fixed in prebaked AMI
            self.public_key = public_key
            # Store agent URL for XDR installation (if provided)
            self.agent_presigned_url = agent_presigned_url if agent_presigned_url else None

            # Create SSM Parameter for DC config (for domain members to reference)
            self.dc_config_param_name = f"/shifter/{environment}/range/{range_id}/dc-config"
            self.dc_config_param = aws.ssm.Parameter(
                f"{name}-dc-config",
                name=self.dc_config_param_name,
                type="SecureString",
                value="{}",  # Empty JSON, will be populated after DC boots
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

    def run_dc_setup(
        self,
        region: Optional[str] = None,
    ) -> pulumi.Output[bool]:
        """Run DC setup via SSM Run Command.

        With prebaked DC AMI, this method only needs to:
        1. Wait for DC's SSM agent to come online (proves DC booted with AD DS ready)
        2. Clean stale DNS records from prebaked AMI
        3. Install XDR agent on DC

        Domain members handle their own domain join in run_setup().

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

        # Store domain config for domain join (captured in closure)
        dc_domain_name = self.domain_name
        dc_admin_password = self.domain_admin_password
        dc_agent_presigned_url = self.agent_presigned_url

        def do_setup(args: tuple) -> bool:
            """Run the domain join synchronously (called within apply)."""
            instance_id, private_ip = args
            pulumi.log.info(f"Prebaked DC instance {instance_id} starting up...")

            # Create executor and orchestrator
            executor = SSMExecutor(region=region)
            orchestrator = SetupOrchestrator(executor=executor)

            try:
                # Wait for SSM agent to come online (proves DC booted with AD DS ready)
                # Windows DC with AD DS can take longer to fully boot - use generous timeout
                pulumi.log.info(f"Waiting for SSM agent on DC {instance_id}...")
                executor.wait_for_agent(instance_id, timeout_seconds=600)
                pulumi.log.info(f"DC {instance_id} is ready (SSM agent online)")

                # Clean stale DNS records from prebaked AMI
                # The AMI contains A records from the build environment that must be removed
                pulumi.log.info(f"Cleaning stale DNS records on DC {instance_id}...")
                dns_cleanup_script = f'''
$ErrorActionPreference = "Stop"
$currentIP = "{private_ip}"
$zone = "{dc_domain_name}"

# Remove stale A records (any IP that isn't the current DC IP)
$staleRecords = Get-DnsServerResourceRecord -ZoneName $zone -RRType A -ErrorAction SilentlyContinue |
    Where-Object {{ $_.HostName -eq "@" -and $_.RecordData.IPv4Address.IPAddressToString -ne $currentIP }}

foreach ($record in $staleRecords) {{
    $oldIP = $record.RecordData.IPv4Address.IPAddressToString
    Write-Host "Removing stale A record: $oldIP"
    Remove-DnsServerResourceRecord -ZoneName $zone -InputObject $record -Force
}}

# Also clean DomainDnsZones and ForestDnsZones
foreach ($subzone in @("DomainDnsZones", "ForestDnsZones")) {{
    $stale = Get-DnsServerResourceRecord -ZoneName $zone -Name $subzone -RRType A -ErrorAction SilentlyContinue |
        Where-Object {{ $_.RecordData.IPv4Address.IPAddressToString -ne $currentIP }}
    foreach ($r in $stale) {{
        Write-Host "Removing stale $subzone A record"
        Remove-DnsServerResourceRecord -ZoneName $zone -InputObject $r -Force -ErrorAction SilentlyContinue
    }}
}}

# Ensure current IP is registered as zone root A record
$existingRecord = Get-DnsServerResourceRecord -ZoneName $zone -RRType A -ErrorAction SilentlyContinue |
    Where-Object {{ $_.HostName -eq "@" -and $_.RecordData.IPv4Address.IPAddressToString -eq $currentIP }}

if (-not $existingRecord) {{
    Write-Host "Adding A record for current IP: $currentIP"
    Add-DnsServerResourceRecordA -ZoneName $zone -Name "@" -IPv4Address $currentIP -TimeToLive 00:10:00
}}

# Force re-registration
Register-DnsClient
ipconfig /registerdns | Out-Null

Write-Host "DNS cleanup complete. Current DC IP: $currentIP"
'''
                result = executor.run_command(
                    instance_id=instance_id,
                    script=dns_cleanup_script,
                    timeout_seconds=60,
                    document_name="AWS-RunPowerShellScript",
                )
                if not result.success:
                    pulumi.log.warn(f"DNS cleanup returned non-zero: {result.stderr}")
                else:
                    pulumi.log.info("DNS cleanup complete")

                # Install XDR agent on DC
                if not dc_agent_presigned_url:
                    raise SetupError(
                        "XDR agent URL is required for DC instances but was not provided"
                    )

                pulumi.log.info(f"Installing XDR agent on DC {instance_id}...")

                xdr_plan = XDRAgentInstallPlan()
                context = xdr_plan.get_context({
                    "agent_presigned_url": dc_agent_presigned_url
                })

                xdr_result = orchestrator.orchestrate(instance_id, xdr_plan, context)
                if not xdr_result.success:
                    raise SetupError(f"XDR agent install failed on DC: {xdr_result.error}")

                pulumi.log.info(f"XDR agent installed successfully on DC {instance_id}")

                return True

            except Exception as e:
                pulumi.log.error(f"Domain setup failed: {e}")
                raise

        # Use apply to run the setup when instance_id and private_ip are resolved
        self.setup_result = pulumi.Output.all(
            self.instance_id, self.private_ip
        ).apply(do_setup)
        return self.setup_result

    def run_setup(
        self,
        region: Optional[str] = None,
        dc_ip: Optional[str] = None,
    ) -> pulumi.Output[bool]:
        """Run setup plan for non-DC instances via SSM Run Command.

        This method handles setup for:
        - Kali (attacker): LinuxBootstrapPlan (hostname + SSH with ssh_user='kali')
        - Linux victims: LinuxBootstrapPlan + LinuxXDRAgentInstallPlan
        - Windows victims: BootstrapPlan + XDRAgentInstallPlan + DomainJoinPlan
          (DomainJoinPlan only runs if join_domain=True and dc_ip is provided)

        DC instances should use run_dc_setup() instead.

        Args:
            region: AWS region (uses default if not provided)
            dc_ip: DC private IP for domain join (only used if join_domain=True)

        Returns:
            pulumi.Output[bool] that resolves to True on success

        Raises:
            SetupError: If any step fails (propagates to Pulumi as stack failure)
        """
        # DC instances use run_dc_setup instead
        if self.role == "dc":
            return pulumi.Output.from_input(True)

        # Capture instance attributes for closure
        instance_role = self.role
        instance_os_type = self.os_type
        instance_hostname = self.hostname
        instance_public_key = self.public_key
        instance_agent_url = self.agent_presigned_url
        instance_ssh_user = self.ssh_user
        instance_join_domain = self.join_domain
        instance_dc_ip = dc_ip

        def do_setup(args: tuple) -> bool:
            """Run the setup synchronously (called within apply)."""
            instance_id, _ = args
            pulumi.log.info(f"Starting setup for {instance_role} instance {instance_id}...")

            # Create executor and orchestrator
            executor = SSMExecutor(region=region)
            orchestrator = SetupOrchestrator(executor=executor)

            # Select SSM document based on OS type
            if instance_os_type in ("kali", "ubuntu", "amazon-linux"):
                document_name = "AWS-RunShellScript"
            else:
                document_name = "AWS-RunPowerShellScript"

            try:
                # Wait for SSM agent to come online
                pulumi.log.info(f"Waiting for SSM agent on {instance_id}...")
                executor.wait_for_agent(instance_id, timeout_seconds=300)
                pulumi.log.info(f"Instance {instance_id} is ready (SSM agent online)")

                # Create context object for plan get_context()
                class InstanceContext:
                    def __init__(self):
                        self.hostname = instance_hostname
                        self.public_key = instance_public_key
                        self.agent_presigned_url = instance_agent_url
                        self.ssh_user = instance_ssh_user

                ctx = InstanceContext()

                # Select and run plans based on role and OS type
                if instance_role == "attacker":
                    # Kali: hostname + SSH setup (uses LinuxBootstrapPlan with ssh_user='kali')
                    plan = LinuxBootstrapPlan()
                    context = plan.get_context(ctx)
                    result = orchestrator.orchestrate(
                        instance_id, plan, context, document_name=document_name
                    )
                    if not result.success:
                        raise SetupError(f"Kali setup failed: {result.error}")
                    pulumi.log.info(f"Kali setup complete for {instance_id}")

                elif instance_role == "victim":
                    if instance_os_type in ("kali", "ubuntu", "amazon-linux"):
                        # Linux victim: Bootstrap + XDR
                        bootstrap_plan = LinuxBootstrapPlan()
                        bootstrap_ctx = bootstrap_plan.get_context(ctx)
                        result = orchestrator.orchestrate(
                            instance_id, bootstrap_plan, bootstrap_ctx, document_name=document_name
                        )
                        if not result.success:
                            raise SetupError(f"Linux bootstrap failed: {result.error}")
                        pulumi.log.info(f"Linux bootstrap complete for {instance_id}")

                        # Install XDR agent
                        if instance_agent_url:
                            xdr_plan = LinuxXDRAgentInstallPlan()
                            xdr_ctx = xdr_plan.get_context({
                                "agent_presigned_url": instance_agent_url
                            })
                            result = orchestrator.orchestrate(
                                instance_id, xdr_plan, xdr_ctx, document_name=document_name
                            )
                            if not result.success:
                                raise SetupError(f"Linux XDR install failed: {result.error}")
                            pulumi.log.info(f"Linux XDR agent installed on {instance_id}")
                        else:
                            pulumi.log.info(f"No XDR agent URL provided for {instance_id}")

                    else:
                        # Windows victim: Bootstrap + XDR
                        bootstrap_plan = BootstrapPlan()
                        bootstrap_ctx = bootstrap_plan.get_context(ctx)
                        result = orchestrator.orchestrate(
                            instance_id, bootstrap_plan, bootstrap_ctx, document_name=document_name
                        )
                        if not result.success:
                            raise SetupError(f"Windows bootstrap failed: {result.error}")
                        pulumi.log.info(f"Windows bootstrap complete for {instance_id}")

                        # Install XDR agent
                        if instance_agent_url:
                            xdr_plan = XDRAgentInstallPlan()
                            xdr_ctx = xdr_plan.get_context({
                                "agent_presigned_url": instance_agent_url
                            })
                            result = orchestrator.orchestrate(
                                instance_id, xdr_plan, xdr_ctx, document_name=document_name
                            )
                            if not result.success:
                                raise SetupError(f"Windows XDR install failed: {result.error}")
                            pulumi.log.info(f"Windows XDR agent installed on {instance_id}")
                        else:
                            pulumi.log.info(f"No XDR agent URL provided for {instance_id}")

                        # Domain join (only for Windows victims with join_domain=True)
                        if instance_join_domain and instance_dc_ip:
                            domain_name = os.environ.get(
                                "DC_DOMAIN_NAME", "internal.shifter"
                            )
                            domain_password = os.environ.get("DC_DOMAIN_PASSWORD", "")

                            if domain_password:
                                pulumi.log.info(
                                    f"Joining domain {domain_name} for {instance_id}..."
                                )
                                domain_join_plan = DomainJoinPlan()
                                dj_context = domain_join_plan.get_context({
                                    "dc_ip": instance_dc_ip,
                                    "domain_name": domain_name,
                                    "domain_admin_password": domain_password,
                                })
                                result = orchestrator.orchestrate(
                                    instance_id,
                                    domain_join_plan,
                                    dj_context,
                                    document_name=document_name,
                                )
                                if not result.success:
                                    raise SetupError(
                                        f"Domain join failed for {instance_id}"
                                    )
                                pulumi.log.info(
                                    f"Domain join complete for {instance_id}"
                                )
                            else:
                                pulumi.log.warn(
                                    f"DC_DOMAIN_PASSWORD not set, skipping domain "
                                    f"join for {instance_id}"
                                )
                        elif instance_join_domain:
                            pulumi.log.info(
                                f"join_domain=True but no dc_ip provided, "
                                f"skipping domain join for {instance_id}"
                            )

                return True

            except Exception as e:
                pulumi.log.error(f"Setup failed for {instance_id}: {e}")
                raise

        # Use apply to run the setup when instance_id and private_ip are resolved
        self.setup_result = pulumi.Output.all(
            self.instance_id, self.private_ip
        ).apply(do_setup)
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
            # DC user_data is minimal - all setup via SSM (BootstrapPlan + DCSetupPlan)
            template = env.get_template("dc_windows.ps1.j2")
            context = {}  # No variables needed - template just logs SSM will handle setup
        elif os_type == "windows":
            # Windows victim - all setup via SSM (BootstrapPlan + XDRAgentInstallPlan)
            template = env.get_template("victim_windows.ps1.j2")
            context = {}  # No variables needed - template just logs SSM will handle setup
        else:
            # Linux victim - all setup via SSM (LinuxBootstrapPlan + LinuxXDRAgentInstallPlan)
            template = env.get_template("victim_linux.sh.j2")
            context = {}  # No variables needed - template just logs SSM will handle setup

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
