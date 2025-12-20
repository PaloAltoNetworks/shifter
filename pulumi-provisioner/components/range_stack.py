"""Range stack component for Shifter range provisioning.

This is the main composition component that brings together:
- Network (subnet)
- Instances (Kali, victims)
"""

from typing import Optional

import pulumi

from ..config import RangeConfig
from .instance import InstanceComponent
from .network import NetworkComponent


class RangeStack(pulumi.ComponentResource):
    """Creates a complete range with all infrastructure.

    This is the main entry point for provisioning a range. It composes:
    - NetworkComponent for subnet creation
    - InstanceComponent(s) for each configured instance

    Attributes:
        network: The network component.
        instances: List of instance components.
        subnet_id: The subnet ID.
        subnet_cidr: The subnet CIDR.
    """

    network: NetworkComponent
    instances: list[InstanceComponent]
    subnet_id: pulumi.Output[str]
    subnet_cidr: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        config: RangeConfig,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        """Create a complete range.

        Args:
            name: Pulumi resource name prefix.
            config: Complete range configuration.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:RangeStack", name, None, opts)

        # Extract CIDR prefix from VPC CIDR (e.g., "10.1.0.0/16" -> "10.1")
        cidr_parts = config.vpc_cidr.split(".")
        cidr_prefix = f"{cidr_parts[0]}.{cidr_parts[1]}"

        # Create network infrastructure
        self.network = NetworkComponent(
            f"{name}-network",
            range_id=config.range_id,
            user_id=config.user_id,
            vpc_id=config.vpc_id,
            cidr_prefix=cidr_prefix,
            subnet_index=config.subnet_index,
            route_table_id=config.route_table_id,
            environment=config.environment,
            availability_zone=config.availability_zone,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.subnet_id = self.network.subnet_id
        self.subnet_cidr = self.network.subnet_cidr

        # Create instances
        self.instances = []
        attacker_count = 0
        victim_count = 0

        for inst_config in config.instances:
            # Determine index for naming
            if inst_config.role == "attacker":
                index = attacker_count
                attacker_count += 1
                security_group_id = config.kali_security_group_id
                ami_id = config.kali_ami_id
            else:
                index = victim_count
                victim_count += 1
                security_group_id = config.victim_security_group_id
                # Select AMI based on OS
                if inst_config.os_type == "windows":
                    ami_id = config.windows_ami_id
                else:
                    ami_id = config.victim_ami_id

            instance_name = f"{name}-{inst_config.role}-{index}"

            instance = InstanceComponent(
                instance_name,
                range_id=config.range_id,
                user_id=config.user_id,
                index=index,
                role=inst_config.role,
                os_type=inst_config.os_type,
                instance_type=inst_config.instance_type,
                subnet_id=self.network.subnet_id,
                security_group_id=security_group_id,
                ami_id=ami_id,
                environment=config.environment,
                instance_profile_name=config.instance_profile_name,
                agent_s3_bucket=config.agent_s3_bucket,
                agent_s3_key=inst_config.agent_s3_key or "",
                agent_presigned_url=inst_config.agent_presigned_url or "",
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[self.network],
                ),
            )

            self.instances.append(instance)

        # Register outputs
        self.register_outputs(
            {
                "subnetId": self.subnet_id,
                "subnetCidr": self.subnet_cidr,
                "instances": [
                    {
                        "role": config.instances[i].role,
                        "os": config.instances[i].os_type,
                        "instance_id": inst.instance_id,
                        "private_ip": inst.private_ip,
                        "ssh_key_secret_arn": inst.ssh_key_secret_arn,
                    }
                    for i, inst in enumerate(self.instances)
                ],
            }
        )

    def get_outputs(self) -> dict:
        """Get all outputs for export to the main Pulumi program.

        Returns:
            Dictionary with all range outputs.
        """
        return {
            "subnet_id": self.subnet_id,
            "subnet_cidr": self.subnet_cidr,
            "instances": [
                {
                    "role": self.instances[i].instance.tags.apply(
                        lambda t: t.get("shifter:role", "unknown")
                    ),
                    "instance_id": inst.instance_id,
                    "private_ip": inst.private_ip,
                    "ssh_key_secret_arn": inst.ssh_key_secret_arn,
                }
                for i, inst in enumerate(self.instances)
            ],
        }
