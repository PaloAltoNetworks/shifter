"""NGFW component for Shifter range provisioning.

This component creates a VM-Series NGFW for a range with:
- Two ENIs (untrust .10, trust .11) for inline traffic inspection
- S3-based bootstrap configuration
- EC2 instance with ENIs attached

The NGFW sits inline between Kali and Victim to generate network telemetry
that can be stitched with XDR endpoint telemetry in XSIAM.
"""

import base64
import os
from pathlib import Path
from typing import Optional

import pulumi
import pulumi_aws as aws
from jinja2 import Environment, FileSystemLoader


class NGFWComponent(pulumi.ComponentResource):
    """Creates a VM-Series NGFW for a range.

    Sits inline between attacker and victim to generate network telemetry
    for stitching with XDR endpoint data.

    Attributes:
        instance: The created EC2 instance resource.
        instance_id: The instance ID.
        untrust_eni: The untrust (Kali-facing) ENI.
        trust_eni: The trust (Victim-facing) ENI.
        untrust_ip: The untrust interface IP (.10).
        trust_ip: The trust interface IP (.11).
        bootstrap_config: The S3 object containing init-cfg.txt.
    """

    instance: aws.ec2.Instance
    instance_id: pulumi.Output[str]
    untrust_eni: aws.ec2.NetworkInterface
    trust_eni: aws.ec2.NetworkInterface
    untrust_ip: pulumi.Output[str]
    trust_ip: pulumi.Output[str]
    bootstrap_config: aws.s3.BucketObject

    def __init__(
        self,
        name: str,
        range_id: int,
        user_id: int,
        subnet_id: pulumi.Input[str],
        security_group_id: str,
        ami_id: str,
        instance_type: str,
        bootstrap_bucket: str,
        cidr_prefix: str,
        subnet_index: int,
        environment: str,
        instance_profile_name: str = "",
        panorama_server: str = "",
        vm_auth_key: str = "",
        panorama_server_2: str = "",
        template_stack: str = "",
        device_group: str = "",
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Create a VM-Series NGFW for a range.

        Args:
            name: Pulumi resource name prefix.
            range_id: The range ID.
            user_id: The user ID.
            subnet_id: Subnet ID to launch in.
            security_group_id: Security group ID for NGFW.
            ami_id: VM-Series AMI ID.
            instance_type: EC2 instance type (m5.xlarge minimum).
            bootstrap_bucket: S3 bucket for bootstrap config.
            cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.0/24).
            subnet_index: The index for the third octet of the CIDR.
            environment: Environment name.
            instance_profile_name: IAM instance profile name (optional).
            panorama_server: Primary Panorama IP/hostname.
            vm_auth_key: VM auth key from Panorama.
            panorama_server_2: Secondary Panorama (HA).
            template_stack: Template stack name.
            device_group: Device group name.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NGFWComponent", name, None, opts)

        # Calculate subnet third octet (same logic as NetworkComponent)
        third_octet = subnet_index + 1

        # Calculate static IPs for ENIs
        untrust_ip = f"{cidr_prefix}.{third_octet}.10"
        trust_ip = f"{cidr_prefix}.{third_octet}.11"

        # Common tags for all resources
        common_tags = {
            "shifter:range_id": str(range_id),
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:role": "ngfw",
            "ManagedBy": "pulumi",
        }

        # Create untrust ENI (Kali-facing, .10)
        self.untrust_eni = aws.ec2.NetworkInterface(
            f"{name}-untrust-eni",
            subnet_id=subnet_id,
            private_ips=[untrust_ip],
            security_groups=[security_group_id],
            source_dest_check=False,  # Required for inline appliance
            tags={
                **common_tags,
                "Name": f"shifter-ngfw-{range_id}-untrust",
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create trust ENI (Victim-facing, .11)
        self.trust_eni = aws.ec2.NetworkInterface(
            f"{name}-trust-eni",
            subnet_id=subnet_id,
            private_ips=[trust_ip],
            security_groups=[security_group_id],
            source_dest_check=False,  # Required for inline appliance
            tags={
                **common_tags,
                "Name": f"shifter-ngfw-{range_id}-trust",
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate bootstrap configuration
        bootstrap_prefix = f"ngfw-bootstrap/{environment}/range-{range_id}"
        init_cfg_content = self._generate_init_cfg(
            hostname=f"shifter-ngfw-{range_id}",
            panorama_server=panorama_server,
            vm_auth_key=vm_auth_key,
            panorama_server_2=panorama_server_2,
            template_stack=template_stack,
            device_group=device_group,
        )

        # Upload init-cfg.txt to S3
        self.bootstrap_config = aws.s3.BucketObject(
            f"{name}-init-cfg",
            bucket=bootstrap_bucket,
            key=f"{bootstrap_prefix}/config/init-cfg.txt",
            content=init_cfg_content,
            tags=common_tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Generate user data for VM-Series bootstrap
        user_data = self._generate_user_data(
            bootstrap_bucket=bootstrap_bucket,
            bootstrap_prefix=bootstrap_prefix,
        )

        instance_name = f"shifter-ngfw-{range_id}"

        # Build instance arguments
        instance_args = {
            "ami": ami_id,
            "instance_type": instance_type,
            # Attach untrust ENI as primary (eth0)
            "network_interfaces": [
                aws.ec2.InstanceNetworkInterfaceArgs(
                    device_index=0,
                    network_interface_id=self.untrust_eni.id,
                ),
                aws.ec2.InstanceNetworkInterfaceArgs(
                    device_index=1,
                    network_interface_id=self.trust_eni.id,
                ),
            ],
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

        # Create instance (depends on bootstrap config being uploaded)
        self.instance = aws.ec2.Instance(
            f"{name}-instance",
            **instance_args,
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[self.bootstrap_config],
            ),
        )

        # Export outputs
        self.instance_id = self.instance.id
        self.untrust_ip = self.untrust_eni.private_ips.apply(lambda ips: ips[0])
        self.trust_ip = self.trust_eni.private_ips.apply(lambda ips: ips[0])

        self.register_outputs(
            {
                "instanceId": self.instance_id,
                "untrustIp": self.untrust_ip,
                "trustIp": self.trust_ip,
            }
        )

    def _generate_init_cfg(
        self,
        hostname: str,
        panorama_server: str = "",
        vm_auth_key: str = "",
        panorama_server_2: str = "",
        template_stack: str = "",
        device_group: str = "",
    ) -> str:
        """Generate VM-Series init-cfg.txt content.

        Args:
            hostname: Hostname for the NGFW.
            panorama_server: Primary Panorama IP/hostname.
            vm_auth_key: VM auth key from Panorama.
            panorama_server_2: Secondary Panorama (HA).
            template_stack: Template stack name.
            device_group: Device group name.

        Returns:
            init-cfg.txt content string.
        """
        # Load Jinja2 templates
        templates_dir = os.environ.get(
            "TEMPLATES_DIR",
            str(Path(__file__).parent.parent / "templates"),
        )
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        template = env.get_template("ngfw_init_cfg.txt.j2")
        return template.render(
            hostname=hostname,
            panorama_server=panorama_server,
            vm_auth_key=vm_auth_key,
            panorama_server_2=panorama_server_2,
            template_stack=template_stack,
            device_group=device_group,
        )

    def _generate_user_data(
        self,
        bootstrap_bucket: str,
        bootstrap_prefix: str,
    ) -> str:
        """Generate VM-Series user data for S3 bootstrap.

        Args:
            bootstrap_bucket: S3 bucket name.
            bootstrap_prefix: S3 key prefix for bootstrap files.

        Returns:
            Base64-encoded user data string.
        """
        # Load Jinja2 templates
        templates_dir = os.environ.get(
            "TEMPLATES_DIR",
            str(Path(__file__).parent.parent / "templates"),
        )
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        template = env.get_template("ngfw_userdata.txt.j2")
        content = template.render(
            bootstrap_bucket=bootstrap_bucket,
            bootstrap_prefix=bootstrap_prefix,
        )
        return base64.b64encode(content.encode()).decode()

    def to_output_dict(self) -> dict:
        """Return NGFW info as a dictionary for export.

        Returns:
            Dictionary with NGFW details.
        """
        return {
            "instance_id": self.instance_id,
            "untrust_ip": self.untrust_ip,
            "trust_ip": self.trust_ip,
        }
