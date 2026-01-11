"""NGFW component for UserNGFW persistent firewall instances.

This component creates the VM-Series NGFW EC2 instance with:
- Management ENI for admin access
- Data ENI for traffic inspection (source_dest_check=False)
- S3 bootstrap configuration
- SSH key pair for post-boot configuration
"""

import os
from pathlib import Path

import pulumi
import pulumi_aws as aws
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jinja2 import Environment, FileSystemLoader


def _generate_ssh_keypair() -> tuple[str, str]:
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


def _get_templates_dir() -> Path:
    """Get the templates directory path."""
    templates_dir = os.environ.get("TEMPLATES_DIR")
    if templates_dir:
        return Path(templates_dir)
    return Path(__file__).parent.parent / "templates"


class NGFWComponent(pulumi.ComponentResource):
    """Creates NGFW EC2 instance with management and data ENIs.

    Attributes:
        instance: The EC2 instance resource.
        mgmt_eni: Management network interface.
        data_eni: Data plane network interface (source_dest_check=False).
        init_cfg: S3 object for bootstrap init-cfg.txt.
        authcodes: S3 object for bootstrap license/authcodes.
        key_pair: EC2 key pair for SSH access.
        ssh_key_secret: Secrets Manager secret for SSH private key.
        instance_id: EC2 instance ID.
        management_ip: Management ENI private IP.
        dataplane_ip: Data plane ENI private IP.
        ssh_key_secret_arn: ARN of the SSH key in Secrets Manager.
    """

    instance: aws.ec2.Instance
    mgmt_eni: aws.ec2.NetworkInterface
    data_eni: aws.ec2.NetworkInterface
    init_cfg: aws.s3.BucketObject
    authcodes: aws.s3.BucketObject
    key_pair: aws.ec2.KeyPair
    ssh_key_secret: aws.secretsmanager.Secret
    instance_id: pulumi.Output[str]
    management_ip: pulumi.Output[str]
    dataplane_ip: pulumi.Output[str]
    ssh_key_secret_arn: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        user_id: int,
        subnet_id: str,
        mgmt_security_group_id: str,
        data_security_group_id: str,
        ami_id: str,
        bootstrap_bucket: str,
        scm_pin_id: str,
        scm_pin_value: str,
        scm_folder_name: str,
        authcode: str,
        request_uuid: str,
        instance_uuid: str,
        instance_type: str = "m5.xlarge",
        environment: str = "dev",
        instance_profile_name: str | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
        """Create NGFW instance with ENIs and bootstrap config.

        Args:
            name: Pulumi resource name prefix.
            user_id: User ID for tagging and bootstrap prefix.
            subnet_id: Subnet ID for ENIs.
            mgmt_security_group_id: Security group for management ENI.
            data_security_group_id: Security group for data ENI.
            ami_id: VM-Series AMI ID.
            bootstrap_bucket: S3 bucket for bootstrap files.
            scm_pin_id: SCM auto-registration PIN ID.
            scm_pin_value: SCM auto-registration PIN value.
            scm_folder_name: SCM folder name (dgname).
            authcode: VM-Series authcode for licensing.
            request_uuid: UUID of the provisioning request (for tagging/correlation).
            instance_uuid: UUID of this NGFW instance (for tagging/correlation).
            instance_type: EC2 instance type (default m5.xlarge).
            environment: Environment name for tagging.
            instance_profile_name: IAM instance profile name.
            opts: Pulumi resource options.

        Raises:
            ValueError: If required uuid parameters are missing.
        """
        super().__init__("shifter:ngfw:NGFWComponent", name, None, opts)

        # Validate required UUID parameters
        if not request_uuid:
            raise ValueError("request_uuid is required for NGFWComponent")
        if not instance_uuid:
            raise ValueError("instance_uuid is required for NGFWComponent")

        # Store instance_uuid for output building
        self._instance_uuid = instance_uuid

        # Build common tags using shared helper
        from components.tags import build_common_tags

        tags = build_common_tags(
            user_id=user_id,
            environment=environment,
            request_uuid=request_uuid,
            unit_type="instance",
            unit_uuid=instance_uuid,
            component="ngfw",
        )
        tags["Name"] = name

        # Create Management ENI
        self.mgmt_eni = aws.ec2.NetworkInterface(
            f"{name}-mgmt-eni",
            subnet_id=subnet_id,
            security_groups=[mgmt_security_group_id],
            description=f"NGFW management interface for user {user_id}",
            tags={**tags, "Name": f"{name}-mgmt"},
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create Data ENI with source_dest_check disabled for inspection
        self.data_eni = aws.ec2.NetworkInterface(
            f"{name}-data-eni",
            subnet_id=subnet_id,
            security_groups=[data_security_group_id],
            source_dest_check=False,  # Required for traffic inspection
            description=f"NGFW data interface for user {user_id}",
            tags={**tags, "Name": f"{name}-data"},
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate SSH key pair for post-boot configuration (Steps 11-14)
        private_key, public_key = _generate_ssh_keypair()

        # Create EC2 KeyPair with the public key
        self.key_pair = aws.ec2.KeyPair(
            f"{name}-keypair",
            key_name=f"ngfw-user-{user_id}",
            public_key=public_key,
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Store private key in Secrets Manager
        self.ssh_key_secret = aws.secretsmanager.Secret(
            f"{name}-ssh-secret",
            name=f"shifter/{environment}/ngfw/{user_id}/ssh-key",
            description=f"SSH private key for NGFW user {user_id}",
            recovery_window_in_days=0,  # Immediate delete for cleanup
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        ssh_key_version = aws.secretsmanager.SecretVersion(
            f"{name}-ssh-secret-version",
            secret_id=self.ssh_key_secret.id,
            secret_string=private_key,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.ssh_key_secret_arn = self.ssh_key_secret.arn

        # Generate bootstrap init-cfg.txt from template
        bootstrap_prefix = f"bootstrap/ngfw/{user_id}"
        hostname = f"ngfw-user-{user_id}"

        templates_dir = _get_templates_dir()
        init_cfg_content = self._render_init_cfg(
            templates_dir=templates_dir,
            hostname=hostname,
            pin_id=scm_pin_id,
            pin_value=scm_pin_value,
            folder_name=scm_folder_name,
        )

        # Upload init-cfg.txt to S3 (config/)
        self.init_cfg = aws.s3.BucketObject(
            f"{name}-init-cfg",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/config/init-cfg.txt",
            content=init_cfg_content,
            content_type="text/plain",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Upload authcodes file to S3 (license/)
        self.authcodes = aws.s3.BucketObject(
            f"{name}-authcodes",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/license/authcodes",
            content=authcode,
            content_type="text/plain",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create empty content/ and software/ folders (required by bootstrap)
        aws.s3.BucketObject(
            f"{name}-content-placeholder",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/content/.keep",
            content="",
            opts=pulumi.ResourceOptions(parent=self),
        )
        aws.s3.BucketObject(
            f"{name}-software-placeholder",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/software/.keep",
            content="",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate user data for VM-Series bootstrap
        bootstrap_path = f"{bootstrap_bucket}/{bootstrap_prefix}"
        user_data = f"vmseries-bootstrap-aws-s3bucket={bootstrap_path}"

        # Create EC2 instance
        instance_args = {
            "ami": ami_id,
            "instance_type": instance_type,
            "key_name": self.key_pair.key_name,
            "network_interfaces": [
                aws.ec2.InstanceNetworkInterfaceArgs(
                    device_index=0,
                    network_interface_id=self.mgmt_eni.id,
                ),
                aws.ec2.InstanceNetworkInterfaceArgs(
                    device_index=1,
                    network_interface_id=self.data_eni.id,
                ),
            ],
            "user_data": user_data,
            "tags": tags,
        }

        if instance_profile_name:
            instance_args["iam_instance_profile"] = instance_profile_name

        self.instance = aws.ec2.Instance(
            f"{name}-instance",
            **instance_args,
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[
                    self.mgmt_eni,
                    self.data_eni,
                    self.init_cfg,
                    self.authcodes,
                    ssh_key_version,
                ],
            ),
        )

        # Export outputs
        self.instance_id = self.instance.id
        self.management_ip = self.mgmt_eni.private_ip
        self.dataplane_ip = self.data_eni.private_ip

        # Register outputs
        self.register_outputs(
            {
                "instanceId": self.instance_id,
                "managementIp": self.management_ip,
                "dataplaneIp": self.dataplane_ip,
                "sshKeySecretArn": self.ssh_key_secret_arn,
            }
        )

    @property
    def uuid(self) -> str:
        """Return the instance UUID for correlation and output building."""
        return self._instance_uuid

    def _render_init_cfg(
        self,
        templates_dir: Path,
        hostname: str,
        pin_id: str,
        pin_value: str,
        folder_name: str,
    ) -> str:
        """Render the init-cfg.txt template with SCM registration credentials.

        Args:
            templates_dir: Path to templates directory.
            hostname: Hostname for the NGFW.
            pin_id: SCM auto-registration PIN ID.
            pin_value: SCM auto-registration PIN value.
            folder_name: SCM folder name (dgname).

        Returns:
            Rendered init-cfg.txt content.
        """
        template_file = templates_dir / "ngfw_init_cfg.txt.j2"
        if template_file.exists():
            # Security: autoescape not needed - PAN-OS config, not HTML
            env = Environment(  # nosec B701  # noqa: S701
                loader=FileSystemLoader(str(templates_dir))
            )
            template = env.get_template("ngfw_init_cfg.txt.j2")
            return template.render(
                hostname=hostname,
                pin_id=pin_id,
                pin_value=pin_value,
                folder_name=folder_name,
            )
        else:
            # Fallback minimal config (without SCM registration)
            return f"type=dhcp-client\nhostname={hostname}\n"
