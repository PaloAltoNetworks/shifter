"""Instance component for Shifter range provisioning.

This component creates EC2 instances for a range with:
- SSH key generation and storage in Secrets Manager (Pulumi-managed)
- User data scripts for setup
- Proper security group attachment
- DC setup orchestration via SSM Run Command (for DC role)

All AWS resources are created via Pulumi to ensure proper lifecycle management.
"""

import asyncio
import base64
import logging
import os
import re
from pathlib import Path

import pulumi
import pulumi_aws as aws
from jinja2 import Environment, FileSystemLoader

from executors.ssm_executor import SSMExecutor
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.bootstrap import BootstrapPlan
from plans.dc_setup import DCSetupPlan
from plans.domain_join import DomainJoinPlan
from plans.linux_bootstrap import LinuxBootstrapPlan
from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from plans.xdr_agent_install import XDRAgentInstallPlan
from utils.crypto import generate_ssh_keypair

logger = logging.getLogger(__name__)


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
    dc_config_param: aws.ssm.Parameter | None
    dc_config_param_name: str | None
    dsrm_password: str | None  # nosec B105 - generated at runtime, not hardcoded
    domain_admin_password: str | None  # nosec B105 - generated at runtime
    domain_name: str | None
    netbios_name: str | None
    hostname: str | None
    public_key: str | None  # Stored for SSM orchestration
    agent_presigned_url: str | None  # For XDR agent installation on DC
    ssh_user: str | None  # SSH user for Linux instances (kali, ubuntu, ec2-user)
    setup_result: pulumi.Output[bool] | None  # Result of DC setup orchestration

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
        request_uuid: str,
        instance_uuid: str,
        instance_profile_name: str = "",
        agent_s3_bucket: str = "",
        agent_s3_key: str = "",
        agent_presigned_url: str = "",
        dc_config: dict | None = None,
        join_domain: bool = False,
        dc_config_param_name: str | None = None,
        opts: pulumi.ResourceOptions | None = None,
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
            request_uuid: UUID of the provisioning request (for tagging/correlation).
            instance_uuid: UUID of this instance (for tagging/correlation).
            instance_profile_name: IAM instance profile name (optional).
            agent_s3_bucket: S3 bucket for agent installer (for victims).
            agent_s3_key: S3 key for agent installer (for victims).
            agent_presigned_url: Pre-generated presigned URL for agent (for victims).
            dc_config: DC configuration dict with domain_name and netbios_name (for DC role).
            join_domain: Whether this instance should join a domain (for domain members).
            dc_config_param_name: SSM parameter path for DC config (for domain members).
            opts: Pulumi resource options.

        Raises:
            ValueError: If required uuid parameters are missing or invalid.
        """
        super().__init__("shifter:range:InstanceComponent", name, None, opts)

        logger.debug(
            "__init__: name=%s range_id=%s role=%s os_type=%s instance_uuid=%s request_uuid=%s",
            name,
            range_id,
            role,
            os_type,
            instance_uuid,
            request_uuid,
        )

        # Validate required UUID parameters
        if not request_uuid:
            raise ValueError("request_uuid is required for InstanceComponent")
        if not instance_uuid:
            raise ValueError("instance_uuid is required for InstanceComponent")

        # Store role, os_type, and uuid for output building (avoids closure issues)
        self.role = role
        self.os_type = os_type
        self._instance_uuid = instance_uuid

        # Build common tags using shared helper
        from components.tags import build_common_tags

        common_tags = build_common_tags(
            user_id=user_id,
            environment=environment,
            request_uuid=request_uuid,
            range_id=range_id,
            unit_type="instance",
            unit_uuid=instance_uuid,
            component="instance",
        )
        # Add instance-specific tags
        common_tags["shifter:role"] = role
        common_tags["shifter:os"] = os_type

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

        # For DC role, generate dynamic domain name per range
        if role == "dc":
            # Read domain admin password from environment (set by Terraform via ECS task definition)
            self.domain_admin_password = os.environ.get("DC_DOMAIN_PASSWORD", "")

            if not self.domain_admin_password:
                raise ValueError("DC_DOMAIN_PASSWORD environment variable is required for DC instances")

            # Fixed domain name from prebaked DC AMI
            # Tradeoff: All ranges share same domain name, but provisioning is fast
            self.domain_name = "internal.shifter"
            self.netbios_name = "INTSHIFTER"
            self.hostname = f"shifter-dc-{range_id}"
            self.dsrm_password = self.domain_admin_password  # Reuse for DSRM
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

        # Create instance (depends on secret being created first for proper ordering)
        instance_tags = {**common_tags, "Name": instance_name}
        self.instance = aws.ec2.Instance(
            f"{name}-instance",
            ami=ami_id,
            instance_type=instance_type,
            subnet_id=subnet_id,
            vpc_security_group_ids=[security_group_id],
            user_data_base64=user_data,
            metadata_options=aws.ec2.InstanceMetadataOptionsArgs(
                http_tokens="required",  # IMDSv2 only
                http_put_response_hop_limit=1,
            ),
            tags=instance_tags,
            iam_instance_profile=instance_profile_name if instance_profile_name else None,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[ssh_key_version]),
        )

        # Export outputs
        self.instance_id = self.instance.id
        self.private_ip = self.instance.private_ip

        logger.info(
            "__init__: created InstanceComponent name=%s role=%s instance_uuid=%s",
            name,
            role,
            instance_uuid,
        )

        self.register_outputs(
            {
                "instanceId": self.instance_id,
                "privateIp": self.private_ip,
                "sshKeySecretArn": self.ssh_key_secret_arn,
            }
        )

    def run_dc_setup(
        self,
        region: str | None = None,
    ) -> pulumi.Output[bool]:
        """Run DC setup via SSM Run Command.

        With AD DS feature AMI (not promoted), this method:
        1. Wait for SSM agent to come online
        2. Set hostname via BootstrapPlan
        3. Promote to Domain Controller via DCSetupPlan (creates unique domain per range)
        4. Install XDR agent on DC

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

        # Store config for closure
        dc_domain_name = self.domain_name
        dc_netbios_name = self.netbios_name
        dc_dsrm_password = self.dsrm_password
        dc_domain_admin_password = self.domain_admin_password
        dc_agent_presigned_url = self.agent_presigned_url

        def do_setup(args: list) -> bool:
            """Run the DC promotion synchronously (called within apply)."""
            instance_id, _ = args[0], args[1]
            pulumi.log.info(f"DC instance {instance_id} starting setup...")
            pulumi.log.info(f"Domain: {dc_domain_name}, NetBIOS: {dc_netbios_name}")

            # Create executor and orchestrator
            executor = SSMExecutor(region=region)
            orchestrator = SetupOrchestrator(executor=executor)

            try:
                # Wait for SSM agent to come online
                pulumi.log.info(f"Waiting for SSM agent on DC {instance_id}...")
                executor.wait_for_agent(instance_id, timeout_seconds=600)
                pulumi.log.info(f"DC {instance_id} SSM agent online")

                # Prebaked DC: Skip hostname change - DC already has correct hostname from AMI
                # The prebaked DC AMI has AD DS promoted with a fixed hostname.
                # Changing the hostname would break AD replication and cause verification to fail.
                pulumi.log.info("Using prebaked DC AMI - skipping hostname change")

                # Verify Domain Controller via DCSetupPlan
                # Prebaked DC has no setup steps, only verification
                pulumi.log.info(f"Verifying Domain Controller ({dc_domain_name})...")
                dc_plan = DCSetupPlan()

                # Validate DC config before proceeding
                if not all([dc_domain_name, dc_netbios_name, dc_dsrm_password, dc_domain_admin_password]):
                    raise SetupError("DC domain config is incomplete - missing required fields")

                # Assert types after validation (mypy narrowing)
                assert dc_domain_name is not None
                assert dc_netbios_name is not None
                assert dc_dsrm_password is not None
                assert dc_domain_admin_password is not None

                # Create config object for DCSetupPlan context
                class DCPromoteConfig:
                    def __init__(
                        self,
                        domain_name: str,
                        netbios_name: str,
                        dsrm_password: str,
                        domain_admin_password: str,
                    ):
                        self.domain_name = domain_name
                        self.netbios_name = netbios_name
                        self.dsrm_password = dsrm_password
                        self.domain_admin_password = domain_admin_password

                dc_config = DCPromoteConfig(
                    dc_domain_name,
                    dc_netbios_name,
                    dc_dsrm_password,
                    dc_domain_admin_password,
                )
                dc_context = dc_plan.get_context(dc_config)
                dc_result = orchestrator.orchestrate(instance_id, dc_plan, dc_context)
                if not dc_result.success:
                    raise SetupError(f"DC verification failed: {dc_result.error}")
                pulumi.log.info("DC verification complete")

                # Install XDR agent on DC
                if dc_agent_presigned_url:
                    pulumi.log.info(f"Installing XDR agent on DC {instance_id}...")
                    xdr_plan = XDRAgentInstallPlan()
                    xdr_context = xdr_plan.get_context({"agent_presigned_url": dc_agent_presigned_url})
                    xdr_result = orchestrator.orchestrate(instance_id, xdr_plan, xdr_context)
                    if not xdr_result.success:
                        raise SetupError(f"XDR agent install failed on DC: {xdr_result.error}")
                    pulumi.log.info("XDR agent installed successfully on DC")
                else:
                    pulumi.log.info("No XDR agent URL provided, skipping XDR install on DC")

                return True

            except Exception as e:
                pulumi.log.error(f"DC setup failed: {e}")
                raise

        # Schedule blocking setup on a separate thread to avoid blocking Pulumi's event loop
        # This enables parallel execution of multiple instance setups
        def schedule_setup(args: list) -> pulumi.Output[bool]:
            coro = asyncio.to_thread(do_setup, args)
            return pulumi.Output.from_input(coro)

        self.setup_result = pulumi.Output.all(self.instance_id, self.private_ip).apply(schedule_setup)
        return self.setup_result

    def run_setup(
        self,
        region: str | None = None,
        dc_ip: str | None = None,
        domain_name: str | None = None,
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
            domain_name: Domain FQDN for domain join (e.g., "range42.lab")

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
        instance_domain_name = domain_name

        def do_setup(args: list) -> bool:
            """Run the setup synchronously (called within apply)."""
            instance_id, _ = args[0], args[1]
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
                    result = orchestrator.orchestrate(instance_id, plan, context, document_name=document_name)
                    if not result.success:
                        raise SetupError(f"Kali setup failed: {result.error}")
                    pulumi.log.info(f"Kali setup complete for {instance_id}")

                elif instance_role == "victim":
                    if instance_os_type in ("kali", "ubuntu", "amazon-linux"):
                        # Linux victim: Bootstrap + XDR
                        bootstrap_plan = LinuxBootstrapPlan()
                        bootstrap_ctx = bootstrap_plan.get_context(ctx)
                        result = orchestrator.orchestrate(
                            instance_id,
                            bootstrap_plan,
                            bootstrap_ctx,
                            document_name=document_name,
                        )
                        if not result.success:
                            raise SetupError(f"Linux bootstrap failed: {result.error}")
                        pulumi.log.info(f"Linux bootstrap complete for {instance_id}")

                        # Install XDR agent
                        if instance_agent_url:
                            xdr_plan = LinuxXDRAgentInstallPlan()
                            xdr_ctx = xdr_plan.get_context({"agent_presigned_url": instance_agent_url})
                            result = orchestrator.orchestrate(
                                instance_id,
                                xdr_plan,
                                xdr_ctx,
                                document_name=document_name,
                            )
                            if not result.success:
                                raise SetupError(f"Linux XDR install failed: {result.error}")
                            pulumi.log.info(f"Linux XDR agent installed on {instance_id}")
                        else:
                            pulumi.log.info(f"No XDR agent URL provided for {instance_id}")

                    else:
                        # Windows victim: Bootstrap + XDR
                        win_bootstrap_plan = BootstrapPlan()
                        win_bootstrap_ctx = win_bootstrap_plan.get_context(ctx)
                        result = orchestrator.orchestrate(
                            instance_id,
                            win_bootstrap_plan,
                            win_bootstrap_ctx,
                            document_name=document_name,
                        )
                        if not result.success:
                            raise SetupError(f"Windows bootstrap failed: {result.error}")
                        pulumi.log.info(f"Windows bootstrap complete for {instance_id}")

                        # Install XDR agent
                        if instance_agent_url:
                            win_xdr_plan = XDRAgentInstallPlan()
                            win_xdr_ctx = win_xdr_plan.get_context({"agent_presigned_url": instance_agent_url})
                            result = orchestrator.orchestrate(
                                instance_id,
                                win_xdr_plan,
                                win_xdr_ctx,
                                document_name=document_name,
                            )
                            if not result.success:
                                raise SetupError(f"Windows XDR install failed: {result.error}")
                            pulumi.log.info(f"Windows XDR agent installed on {instance_id}")
                        else:
                            pulumi.log.info(f"No XDR agent URL provided for {instance_id}")

                        # Domain join (only for Windows victims with join_domain=True)
                        if instance_join_domain and instance_dc_ip and instance_domain_name:
                            domain_password = os.environ.get("DC_DOMAIN_PASSWORD", "")

                            if domain_password:
                                pulumi.log.info(f"Joining domain {instance_domain_name} for {instance_id}...")
                                domain_join_plan = DomainJoinPlan()
                                dj_context = domain_join_plan.get_context(
                                    {
                                        "dc_ip": instance_dc_ip,
                                        "domain_name": instance_domain_name,
                                        "domain_admin_password": domain_password,
                                    }
                                )
                                result = orchestrator.orchestrate(
                                    instance_id,
                                    domain_join_plan,
                                    dj_context,
                                    document_name=document_name,
                                )
                                if not result.success:
                                    raise SetupError(f"Domain join failed for {instance_id}")
                                pulumi.log.info(f"Domain join complete for {instance_id}")
                            else:
                                pulumi.log.warn(f"DC_DOMAIN_PASSWORD not set, skipping domain join for {instance_id}")
                        elif instance_join_domain:
                            pulumi.log.info(
                                f"join_domain=True but no dc_ip/domain_name, skipping domain join for {instance_id}"
                            )

                return True

            except Exception as e:
                pulumi.log.error(f"Setup failed for {instance_id}: {e}")
                raise

        # Schedule blocking setup on a separate thread to avoid blocking Pulumi's event loop
        # This enables parallel execution of multiple instance setups
        def schedule_setup(args: list) -> pulumi.Output[bool]:
            coro = asyncio.to_thread(do_setup, args)
            return pulumi.Output.from_input(coro)

        self.setup_result = pulumi.Output.all(self.instance_id, self.private_ip).apply(schedule_setup)
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
        dc_config: dict | None = None,
        join_domain: bool = False,
        member_dc_config_param_name: str | None = None,
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
        logger.debug(
            "_generate_user_data: role=%s os_type=%s range_id=%s index=%s join_domain=%s",
            role,
            os_type,
            range_id,
            index,
            join_domain,
        )

        # Load Jinja2 templates
        # Use TEMPLATES_DIR env var if set, otherwise default to relative path
        templates_dir = os.environ.get(
            "TEMPLATES_DIR",
            str(Path(__file__).parent.parent / "templates"),
        )
        # Security: autoescape=False is required - these are shell/PowerShell templates, not HTML.
        # XSS is not applicable since output goes to EC2 user-data, not web browsers.
        env = Environment(  # nosec B701
            loader=FileSystemLoader(templates_dir),
            autoescape=False,  # noqa: S701
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

    @property
    def uuid(self) -> str:
        """Return the instance UUID for correlation and output building."""
        return self._instance_uuid

    def to_output_dict(self) -> dict:
        """Return instance info as a dictionary for export.

        Returns:
            Dictionary with instance details including uuid for DB correlation.
        """
        return {
            "uuid": self._instance_uuid,
            "instance_id": self.instance_id,
            "private_ip": self.private_ip,
            "ssh_key_secret_arn": self.ssh_key_secret_arn,
        }
