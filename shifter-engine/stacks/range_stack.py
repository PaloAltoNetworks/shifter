"""Range stack component for Shifter range provisioning.

This is the main composition component that brings together:
- Network (subnet)
- Instances (Kali, victims, DC)

DC instances are created first to ensure domain controllers are available
before domain member instances that depend on them.
"""

from typing import Optional

import pulumi

from config import InstanceConfig, RangeConfig
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

        self._validate_config(config)
        self._create_network(name, config)
        dc_components = self._create_all_instances(name, config)
        self._run_all_setup(dc_components, config)
        self._register_outputs()

    def _build_instance_output(self, instance: InstanceComponent) -> dict:
        """Build output dict for a single instance.

        Args:
            instance: The instance component.

        Returns:
            Dictionary with instance output fields.
        """
        return {
            "role": instance.role,
            "os": instance.os_type,
            "instance_id": instance.instance_id,
            "private_ip": instance.private_ip,
            "ssh_key_secret_arn": instance.ssh_key_secret_arn,
        }

    def _register_outputs(self) -> None:
        """Build and register Pulumi outputs."""
        instance_outputs = [self._build_instance_output(inst) for inst in self.instances]

        outputs = {
            "subnetId": self.subnet_id,
            "subnetCidr": self.subnet_cidr,
            "instances": instance_outputs,
        }
        if self.dc_config_param_name:
            outputs["dcConfigParamName"] = self.dc_config_param_name

        self.register_outputs(outputs)

    def _run_all_setup(
        self, dc_components: list[InstanceComponent], config: RangeConfig
    ) -> None:
        """Run setup for all instances (non-DC first, then DCs).

        Args:
            dc_components: List of DC instance components.
            config: Range configuration.
        """
        # Run setup for non-DC instances
        other_configs = [inst for inst in config.instances if inst.role != "dc"]
        for inst_config, instance in zip(other_configs, self.instances[len(dc_components):]):
            # Domain-joining instances get DC's private_ip for domain join
            if inst_config.join_domain and dc_components:
                dc_components[0].private_ip.apply(
                    lambda ip, inst=instance: inst.run_setup(dc_ip=ip)
                )
            else:
                instance.run_setup()

        # Run DC setup
        for dc_instance in dc_components:
            dc_instance.run_dc_setup()

    def _create_all_instances(
        self, name: str, config: RangeConfig
    ) -> list[InstanceComponent]:
        """Create all instances (DCs first, then others).

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration.

        Returns:
            List of DC components for setup phase.
        """
        # Separate instances by role for dependency ordering
        dc_configs = [inst for inst in config.instances if inst.role == "dc"]
        other_configs = [inst for inst in config.instances if inst.role != "dc"]

        # Create instances list and role counters
        self.instances = []
        dc_components: list[InstanceComponent] = []
        counters = {"dc": 0, "attacker": 0, "victim": 0}

        # Initialize dc_config_param_name (will be set if DC exists)
        self.dc_config_param_name = None

        # Create DC instances first
        for inst_config in dc_configs:
            dc_instance = self._create_instance(name, inst_config, config, counters)
            dc_components.append(dc_instance)
            self.instances.append(dc_instance)

        # Store dc_config_param_name from first DC
        if dc_components:
            self.dc_config_param_name = dc_components[0].dc_config_param_name

        # Create other instances (attackers, victims)
        for inst_config in other_configs:
            instance = self._create_instance(name, inst_config, config, counters)
            self.instances.append(instance)

        return dc_components

    def _create_instance(
        self,
        name: str,
        inst_config: InstanceConfig,
        config: RangeConfig,
        counters: dict[str, int],
    ) -> InstanceComponent:
        """Create a single instance with role-appropriate parameters.

        Args:
            name: Pulumi resource name prefix.
            inst_config: Instance configuration.
            config: Range configuration.
            counters: Mutable dict tracking indices per role.

        Returns:
            Created InstanceComponent.
        """
        ami_id, security_group_id, index = self._resolve_instance_params(
            inst_config, config, counters
        )
        instance_name = f"{name}-{inst_config.role}-{index}"

        # Build kwargs - DC instances have dc_config, others have join_domain
        kwargs = {
            "range_id": config.range_id,
            "user_id": config.user_id,
            "index": index,
            "role": inst_config.role,
            "os_type": inst_config.os_type,
            "instance_type": inst_config.instance_type,
            "subnet_id": self.network.subnet_id,
            "security_group_id": security_group_id,
            "ami_id": ami_id,
            "environment": config.environment,
            "instance_profile_name": config.instance_profile_name,
            "agent_s3_bucket": config.agent_s3_bucket,
            "agent_s3_key": inst_config.agent_s3_key or "",
            "agent_presigned_url": inst_config.agent_presigned_url or "",
            "opts": pulumi.ResourceOptions(parent=self, depends_on=[self.network]),
        }

        if inst_config.role == "dc":
            kwargs["dc_config"] = inst_config.dc_config
        else:
            kwargs["join_domain"] = inst_config.join_domain
            kwargs["dc_config_param_name"] = None  # DC triggers domain join via SSM

        return InstanceComponent(instance_name, **kwargs)

    def _resolve_instance_params(
        self, inst_config: InstanceConfig, config: RangeConfig, counters: dict[str, int]
    ) -> tuple[str, str, int]:
        """Resolve AMI, security group, and index for an instance.

        Args:
            inst_config: Instance configuration.
            config: Range configuration with AMI/SG IDs.
            counters: Mutable dict tracking indices per role.

        Returns:
            Tuple of (ami_id, security_group_id, index).
        """
        role = inst_config.role
        index = counters[role]
        counters[role] += 1

        if role == "dc":
            return config.dc_ami_id, config.dc_security_group_id, index
        elif role == "attacker":
            return config.kali_ami_id, config.kali_security_group_id, index
        else:  # victim
            ami_id = config.windows_ami_id if inst_config.os_type == "windows" else config.victim_ami_id
            return ami_id, config.victim_security_group_id, index

    def _create_network(self, name: str, config: RangeConfig) -> None:
        """Create network infrastructure and assign subnet attributes.

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration.
        """
        cidr_prefix = self._extract_cidr_prefix(config.vpc_cidr)
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

    def _validate_config(self, config: RangeConfig) -> None:
        """Validate config has required fields for instance types present.

        Args:
            config: Range configuration to validate.

        Raises:
            ValueError: If required fields are missing for configured instance types.
        """
        has_dc = any(inst.role == "dc" for inst in config.instances)
        if has_dc:
            if not config.dc_security_group_id:
                raise ValueError("dc_security_group_id is required for DC instances")
            if not config.dc_ami_id:
                raise ValueError("dc_ami_id is required for DC instances")

    def _extract_cidr_prefix(self, vpc_cidr: str) -> str:
        """Extract first two octets from VPC CIDR.

        Args:
            vpc_cidr: VPC CIDR block (e.g., "10.1.0.0/16").

        Returns:
            First two octets (e.g., "10.1").
        """
        parts = vpc_cidr.split(".")
        return f"{parts[0]}.{parts[1]}"

    def get_outputs(self) -> dict:
        """Get all outputs for export to the main Pulumi program.

        Returns:
            Dictionary with all range outputs including dc_config_param_name if DC exists.
        """
        return {
            "subnet_id": self.subnet_id,
            "subnet_cidr": self.subnet_cidr,
            "instances": [self._build_instance_output(inst) for inst in self.instances],
            "dc_config_param_name": self.dc_config_param_name,
        }
