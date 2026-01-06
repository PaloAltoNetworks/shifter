"""NGFW component for UserNGFW persistent firewall instances.

This component creates the VM-Series NGFW EC2 instance with:
- Management ENI for admin access
- Data ENI for traffic inspection (source_dest_check=False)
- S3 bootstrap configuration
"""

import os
from pathlib import Path

import pulumi
import pulumi_aws as aws
from jinja2 import Environment, FileSystemLoader


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
        instance_id: EC2 instance ID.
        management_ip: Management ENI private IP.
        dataplane_ip: Data plane ENI private IP.
    """

    instance: aws.ec2.Instance
    mgmt_eni: aws.ec2.NetworkInterface
    data_eni: aws.ec2.NetworkInterface
    init_cfg: aws.s3.BucketObject
    instance_id: pulumi.Output[str]
    management_ip: pulumi.Output[str]
    dataplane_ip: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        user_id: int,
        subnet_id: str,
        security_group_id: str,
        ami_id: str,
        bootstrap_bucket: str,
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
            security_group_id: Security group for NGFW.
            ami_id: VM-Series AMI ID.
            bootstrap_bucket: S3 bucket for bootstrap files.
            instance_type: EC2 instance type (default m5.xlarge).
            environment: Environment name for tagging.
            instance_profile_name: IAM instance profile name.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:ngfw:NGFWComponent", name, None, opts)

        tags = {
            "Name": f"{name}",
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:component": "ngfw",
        }

        # Create Management ENI
        self.mgmt_eni = aws.ec2.NetworkInterface(
            f"{name}-mgmt-eni",
            subnet_id=subnet_id,
            security_groups=[security_group_id],
            description=f"NGFW management interface for user {user_id}",
            tags={**tags, "Name": f"{name}-mgmt"},
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create Data ENI with source_dest_check disabled for traffic inspection
        self.data_eni = aws.ec2.NetworkInterface(
            f"{name}-data-eni",
            subnet_id=subnet_id,
            security_groups=[security_group_id],
            source_dest_check=False,  # Required for traffic inspection
            description=f"NGFW data interface for user {user_id}",
            tags={**tags, "Name": f"{name}-data"},
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate bootstrap init-cfg.txt from template
        bootstrap_prefix = f"ngfw/{user_id}"
        hostname = f"ngfw-user-{user_id}"

        templates_dir = _get_templates_dir()
        init_cfg_content = self._render_init_cfg(templates_dir, hostname)

        # Upload init-cfg.txt to S3
        self.init_cfg = aws.s3.BucketObject(
            f"{name}-init-cfg",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/config/init-cfg.txt",
            content=init_cfg_content,
            content_type="text/plain",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate user data for VM-Series bootstrap
        user_data = f"vmseries-bootstrap-aws-s3bucket={bootstrap_bucket}/{bootstrap_prefix}"

        # Create EC2 instance
        instance_args = {
            "ami": ami_id,
            "instance_type": instance_type,
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
                depends_on=[self.mgmt_eni, self.data_eni, self.init_cfg],
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
            }
        )

    def _render_init_cfg(self, templates_dir: Path, hostname: str) -> str:
        """Render the init-cfg.txt template.

        Args:
            templates_dir: Path to templates directory.
            hostname: Hostname for the NGFW.

        Returns:
            Rendered init-cfg.txt content.
        """
        template_file = templates_dir / "ngfw_init_cfg.txt.j2"
        if template_file.exists():
            # Security: autoescape not needed - this is PAN-OS config, not HTML.
            env = Environment(loader=FileSystemLoader(str(templates_dir)))  # nosec B701  # noqa: S701
            template = env.get_template("ngfw_init_cfg.txt.j2")
            return template.render(
                hostname=hostname,
                auth_key="",  # Will be set during provisioning
                panorama_server="",
                device_group="",
                template_stack="",
            )
        else:
            # Fallback minimal config
            return f"type=dhcp-client\nhostname={hostname}\n"
