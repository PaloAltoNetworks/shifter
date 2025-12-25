"""Range stack component for Shifter range provisioning.

This is the main composition component that brings together:
- Network (subnet)
- Instances (Kali, victims, DC)

DC instances are created first to ensure domain controllers are available
before domain member instances that depend on them.
"""

from typing import Optional

import pulumi

from config import RangeConfig
from components.instance import InstanceComponent
from components.network import NetworkComponent


class RangeStack(pulumi.ComponentResource):
    """Creates a complete range with all infrastructure.

    This is the main entry point for provisioning a range. It composes:
    - NetworkComponent for subnet creation
    - InstanceComponent(s) for each configured instance

    DC instances are created first (dependency ordering) to ensure the domain
    controller is available before domain members attempt to join.

    Attributes:
        network: The network component.
        instances: List of instance components.
        subnet_id: The subnet ID.
        subnet_cidr: The subnet CIDR.
        dc_config_param_name: SSM parameter path for DC config (None if no DC).
    """

    network: NetworkComponent
    instances: list[InstanceComponent]
    subnet_id: pulumi.Output[str]
    subnet_cidr: pulumi.Output[str]
    dc_config_param_name: Optional[str]

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

        # Separate instances by role for dependency ordering
        # DC instances must be created first so domain members can depend on them
        dc_configs = [inst for inst in config.instances if inst.role == "dc"]
        other_configs = [inst for inst in config.instances if inst.role != "dc"]

        # Create instances list and role counters
        self.instances = []
        dc_components: list[InstanceComponent] = []
        attacker_count = 0
        victim_count = 0
        dc_count = 0

        # Initialize dc_config_param_name (will be set if DC exists)
        self.dc_config_param_name = None

        # Create DC instances first
        for inst_config in dc_configs:
            index = dc_count
            dc_count += 1
            security_group_id = config.dc_security_group_id or config.victim_security_group_id
            ami_id = config.windows_ami_id

            instance_name = f"{name}-dc-{index}"

            dc_instance = InstanceComponent(
                instance_name,
                range_id=config.range_id,
                user_id=config.user_id,
                index=index,
                role="dc",
                os_type=inst_config.os_type,
                instance_type=inst_config.instance_type,
                subnet_id=self.network.subnet_id,
                security_group_id=security_group_id,
                ami_id=ami_id,
                environment=config.environment,
                instance_profile_name=config.instance_profile_name,
                agent_s3_bucket=config.agent_s3_bucket,
                agent_s3_key="",
                agent_presigned_url="",
                dc_config=inst_config.dc_config,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[self.network],
                ),
            )

            # Run DC setup via SSM orchestration (AD DS install, reboot, promote)
            dc_instance.run_dc_setup()

            dc_components.append(dc_instance)
            self.instances.append(dc_instance)

        # Store dc_config_param_name from first DC (for traceability and domain members)
        if dc_components:
            self.dc_config_param_name = dc_components[0].dc_config_param_name

        # Create other instances (attackers, victims) with DC dependency if applicable
        for inst_config in other_configs:
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

            # Determine dependencies - domain members depend on DC
            depends_on = [self.network]
            if inst_config.join_domain and dc_components:
                depends_on.extend(dc_components)

            # Determine dc_config_param_name for domain members
            member_dc_config_param_name = None
            if inst_config.join_domain and dc_components:
                member_dc_config_param_name = self.dc_config_param_name

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
                join_domain=inst_config.join_domain,
                dc_config_param_name=member_dc_config_param_name,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=depends_on,
                ),
            )

            self.instances.append(instance)

        # Build instance output list using stored role/os_type to avoid closure issues
        # (using .apply() in a loop would capture loop variable by reference)
        instance_outputs = []
        for inst in self.instances:
            instance_outputs.append({
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            })

        # Register outputs
        outputs = {
            "subnetId": self.subnet_id,
            "subnetCidr": self.subnet_cidr,
            "instances": instance_outputs,
        }
        if self.dc_config_param_name:
            outputs["dcConfigParamName"] = self.dc_config_param_name

        self.register_outputs(outputs)

    def get_outputs(self) -> dict:
        """Get all outputs for export to the main Pulumi program.

        Returns:
            Dictionary with all range outputs including dc_config_param_name if DC exists.
        """
        outputs = {
            "subnet_id": self.subnet_id,
            "subnet_cidr": self.subnet_cidr,
            "instances": [
                {
                    "role": inst.role,
                    "os": inst.os_type,
                    "instance_id": inst.instance_id,
                    "private_ip": inst.private_ip,
                    "ssh_key_secret_arn": inst.ssh_key_secret_arn,
                }
                for inst in self.instances
            ],
            "dc_config_param_name": self.dc_config_param_name,
        }
        return outputs
