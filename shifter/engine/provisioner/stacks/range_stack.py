"""Range stack component for Shifter range provisioning.

This is the main composition component that brings together:
- Networks (multiple subnets with SG, RT, GWLB per subnet)
- Instances (Kali, victims, DC) placed in their designated subnets

DC instances are created first to ensure domain controllers are available
before domain member instances that depend on them.
"""

import logging
from typing import Any

import pulumi

from components.instance import InstanceComponent
from components.network import NetworkComponent, allocate_subnets
from config import InstanceConfig, RangeConfig

logger = logging.getLogger(__name__)


class RangeStack(pulumi.ComponentResource):
    """Creates a complete range with all infrastructure.

    This is the main entry point for provisioning a range. It composes:
    - NetworkComponent(s) for each logical subnet (with SG, RT, GWLB per subnet)
    - InstanceComponent(s) for each configured instance, placed in designated subnets

    DC instances are created first (dependency ordering) to ensure the domain
    controller is available before domain members attempt to join.

    Attributes:
        networks: Dict mapping subnet name to NetworkComponent.
        instances: List of all instance components.
        dc_config_param_name: SSM parameter path for DC config (None if no DC).
    """

    networks: dict[str, NetworkComponent]
    instances: list[tuple[InstanceComponent, str]]  # (instance, subnet_name)
    dc_config_param_name: str | None

    def __init__(
        self,
        name: str,
        config: RangeConfig,
        opts: pulumi.ResourceOptions | None = None,
    ) -> None:
        """Create a complete range.

        Args:
            name: Pulumi resource name prefix.
            config: Complete range configuration.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:RangeStack", name, None, opts)

        logger.info(
            "Creating RangeStack: name=%s, subnets=%d, request_uuid=%s",
            name,
            len(config.subnets),
            config.request_uuid,
        )

        self._validate_config(config)
        self._create_networks(name, config)
        dc_components = self._create_all_instances(name, config)
        self._run_all_setup(dc_components, config)
        self._register_outputs()

        logger.info(
            "RangeStack created: %d networks, %d instances",
            len(self.networks),
            len(self.instances),
        )

    def _build_instance_output(
        self, instance: InstanceComponent, subnet_name: str
    ) -> dict[str, str | pulumi.Output[str]]:
        """Build output dict for a single instance.

        Args:
            instance: The instance component.
            subnet_name: Name of the subnet this instance is in.

        Returns:
            Dictionary with instance output fields including uuid for DB correlation.
        """
        return {
            "uuid": instance.uuid,
            "role": instance.role,
            "os": instance.os_type,
            "subnet_name": subnet_name,
            "instance_id": instance.instance_id,
            "private_ip": instance.private_ip,
            "ssh_key_secret_arn": instance.ssh_key_secret_arn,
        }

    def _register_outputs(self) -> None:
        """Build and register Pulumi outputs."""
        # Build instance outputs with subnet_name
        instance_outputs = [self._build_instance_output(inst, subnet_name) for inst, subnet_name in self.instances]

        # Build subnets output dict
        subnets_output: dict[str, dict[str, pulumi.Output[str]]] = {
            name: {
                "subnet_id": net.subnet_id,
                "subnet_cidr": net.subnet_cidr,
                "security_group_id": net.security_group_id,
                "route_table_id": net.route_table_id,
                "gwlb_endpoint_id": net.gwlb_endpoint_id,
            }
            for name, net in self.networks.items()
        }

        outputs: dict[str, object] = {
            "subnets": subnets_output,
            "instances": instance_outputs,
        }
        if self.dc_config_param_name:
            outputs["dcConfigParamName"] = self.dc_config_param_name

        self.register_outputs(outputs)

    def _run_all_setup(self, dc_components: list[InstanceComponent], config: RangeConfig) -> None:
        """Run setup for all instances (non-DC first, then DCs).

        Args:
            dc_components: List of DC instance components.
            config: Range configuration.
        """
        # Build a flat list of (instance_config, instance_component) pairs for non-DCs
        # by iterating through subnets
        non_dc_pairs: list[tuple[InstanceConfig, InstanceComponent]] = []
        dc_count = len(dc_components)
        instance_idx = dc_count  # Skip DC instances at the front

        for subnet_config in config.subnets:
            for inst_config in subnet_config.instances:
                if inst_config.role != "dc":
                    instance, _ = self.instances[instance_idx]
                    non_dc_pairs.append((inst_config, instance))
                    instance_idx += 1

        # Run setup for non-DC instances
        for inst_config, instance in non_dc_pairs:
            # Domain-joining instances get DC's private_ip for domain join
            if inst_config.join_domain and dc_components:

                def setup_with_dc_ip(ip: str, inst: InstanceComponent = instance) -> None:
                    inst.run_setup(dc_ip=ip)

                dc_components[0].private_ip.apply(setup_with_dc_ip)
            else:
                instance.run_setup()

        # Run DC setup
        for dc_instance in dc_components:
            dc_instance.run_dc_setup()

    def _create_all_instances(self, name: str, config: RangeConfig) -> list[InstanceComponent]:
        """Create all instances (DCs first, then others).

        Iterates through subnets and creates instances in their designated subnet.
        DC instances are created first across all subnets to ensure domain controllers
        are available before domain members.

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration.

        Returns:
            List of DC components for setup phase.
        """
        self.instances = []
        dc_components: list[InstanceComponent] = []
        counters: dict[str, int] = {"dc": 0, "attacker": 0, "victim": 0}

        # Initialize dc_config_param_name (will be set if DC exists)
        self.dc_config_param_name = None

        # First pass: Create DC instances from all subnets (DCs go first)
        for subnet_config in config.subnets:
            network = self.networks[subnet_config.name]
            for inst_config in subnet_config.instances:
                if inst_config.role == "dc":
                    dc_instance = self._create_instance(
                        name, inst_config, config, counters, network, subnet_config.name
                    )
                    dc_components.append(dc_instance)
                    self.instances.append((dc_instance, subnet_config.name))

        # Store dc_config_param_name from first DC
        if dc_components:
            self.dc_config_param_name = dc_components[0].dc_config_param_name

        # Second pass: Create non-DC instances from all subnets
        for subnet_config in config.subnets:
            network = self.networks[subnet_config.name]
            for inst_config in subnet_config.instances:
                if inst_config.role != "dc":
                    instance = self._create_instance(name, inst_config, config, counters, network, subnet_config.name)
                    self.instances.append((instance, subnet_config.name))

        logger.debug(
            "Created %d instances (%d DCs) across %d subnets",
            len(self.instances),
            len(dc_components),
            len(config.subnets),
        )

        return dc_components

    def _create_instance(
        self,
        name: str,
        inst_config: InstanceConfig,
        config: RangeConfig,
        counters: dict[str, int],
        network: NetworkComponent,
        subnet_name: str,
    ) -> InstanceComponent:
        """Create a single instance with role-appropriate parameters.

        Args:
            name: Pulumi resource name prefix.
            inst_config: Instance configuration.
            config: Range configuration.
            counters: Mutable dict tracking indices per role.
            network: NetworkComponent for this instance's subnet.
            subnet_name: Name of the subnet for logging/tagging.

        Returns:
            Created InstanceComponent.
        """
        ami_id, index = self._resolve_instance_params(inst_config, config, counters)
        instance_name = f"{name}-{inst_config.role}-{index}"

        logger.debug(
            "Creating instance %s in subnet %s (role=%s, os=%s)",
            instance_name,
            subnet_name,
            inst_config.role,
            inst_config.os_type,
        )

        # Build kwargs - DC instances have dc_config, others have join_domain
        # subnet_id and security_group_id come from the network component
        kwargs: dict[str, Any] = {
            "range_id": config.range_id,
            "user_id": config.user_id,
            "index": index,
            "role": inst_config.role,
            "os_type": inst_config.os_type,
            "instance_type": inst_config.instance_type,
            "subnet_id": network.subnet_id,
            "security_group_id": network.security_group_id,
            "ami_id": ami_id,
            "environment": config.environment,
            "request_uuid": config.request_uuid,
            "instance_uuid": inst_config.uuid,
            "instance_profile_name": config.instance_profile_name,
            "agent_s3_bucket": config.agent_s3_bucket,
            "agent_s3_key": inst_config.agent_s3_key or "",
            "agent_presigned_url": inst_config.agent_presigned_url or "",
            "opts": pulumi.ResourceOptions(parent=self, depends_on=[network]),
        }

        if inst_config.role == "dc":
            kwargs["dc_config"] = inst_config.dc_config
        else:
            kwargs["join_domain"] = inst_config.join_domain
            kwargs["dc_config_param_name"] = None  # DC triggers domain join via SSM

        return InstanceComponent(instance_name, **kwargs)

    def _resolve_instance_params(
        self,
        inst_config: InstanceConfig,
        config: RangeConfig,
        counters: dict[str, int],
    ) -> tuple[str, int]:
        """Resolve AMI and index for an instance.

        Security group now comes from the subnet's NetworkComponent.

        Args:
            inst_config: Instance configuration.
            config: Range configuration with AMI IDs.
            counters: Mutable dict tracking indices per role.

        Returns:
            Tuple of (ami_id, index).
        """
        role = inst_config.role
        index = counters[role]
        counters[role] += 1

        if role == "dc":
            return config.dc_ami_id, index
        elif role == "attacker":
            return config.kali_ami_id, index
        else:  # victim
            if inst_config.os_type == "windows":
                return config.windows_ami_id, index
            return config.victim_ami_id, index

    def _create_networks(self, name: str, config: RangeConfig) -> None:
        """Create network infrastructure for all subnets.

        Creates one NetworkComponent per logical subnet, each with its own
        security group, route table, and optional GWLB endpoint.

        Pre-allocates all subnet CIDRs atomically before creating any
        NetworkComponent to prevent race conditions where multiple subnets
        get the same CIDR.

        After all networks are created, adds inter-subnet routes to force
        all inter-subnet traffic through the GWLB/NGFW.

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration with subnets list.
        """
        self.networks = {}
        cidr_prefix = self._extract_cidr_prefix(config.vpc_cidr)
        subnet_count = len(config.subnets)

        logger.info(
            "Creating %d networks for range %d",
            subnet_count,
            config.range_id,
        )

        # Pre-allocate all subnet CIDRs atomically to prevent race conditions
        # This holds the advisory lock for the entire allocation
        allocated_cidrs = allocate_subnets(
            vpc_id=config.vpc_id,
            cidr_prefix=cidr_prefix,
            count=subnet_count,
            subnet_size=28,  # All range subnets use /28
        )

        logger.info(
            "Pre-allocated %d CIDRs: %s",
            len(allocated_cidrs),
            allocated_cidrs,
        )

        for idx, subnet_config in enumerate(config.subnets):
            network_name = f"{name}-net-{subnet_config.name}"
            subnet_cidr = allocated_cidrs[idx]

            logger.debug(
                "Creating network %s (uuid=%s, cidr=%s, gwlb=%s)",
                network_name,
                subnet_config.uuid,
                subnet_cidr,
                "enabled" if config.gwlb_service_name else "disabled",
            )

            network = NetworkComponent(
                network_name,
                range_id=config.range_id,
                user_id=config.user_id,
                vpc_id=config.vpc_id,
                vpc_cidr=config.vpc_cidr,
                cidr_prefix=cidr_prefix,
                environment=config.environment,
                availability_zone=config.availability_zone,
                subnet_name=subnet_config.name,
                subnet_uuid=subnet_config.uuid,
                request_uuid=config.request_uuid,
                subnet_size=28,  # All range subnets use /28
                gwlb_service_name=config.gwlb_service_name,
                s3_endpoint_id=config.s3_endpoint_id,
                portal_vpc_cidr=config.portal_vpc_cidr,
                portal_vpc_peering_id=config.portal_vpc_peering_id,
                allocated_cidr=subnet_cidr,
                opts=pulumi.ResourceOptions(parent=self),
            )
            self.networks[subnet_config.name] = network

        # Add inter-subnet routes to force all inter-subnet traffic through GWLB
        self._add_inter_subnet_routes(name, config)

    def _get_connected_pairs(self, config: RangeConfig) -> list[tuple[str, str]]:
        """Build deduplicated list of connected subnet pairs from config.

        Connection is symmetric: if A lists B in connected_to OR B lists A,
        they're connected bidirectionally. Uses frozenset for O(1) deduplication.

        Args:
            config: Range configuration with subnets.

        Returns:
            List of (subnet_a, subnet_b) tuples, sorted alphabetically,
            with no duplicates.
        """
        subnet_names = {s.name for s in config.subnets}
        seen: set[frozenset[str]] = set()
        pairs: list[tuple[str, str]] = []

        for subnet in config.subnets:
            src = subnet.name
            for dst in subnet.connected_to:
                if dst not in subnet_names:
                    logger.warning(
                        "Subnet '%s' references unknown subnet '%s' in connected_to",
                        src,
                        dst,
                    )
                    continue  # Skip invalid references
                pair_key = frozenset([src, dst])
                if pair_key not in seen:
                    seen.add(pair_key)
                    # Sort for consistent naming
                    a, b = sorted([src, dst])
                    pairs.append((a, b))

        return pairs

    def _add_inter_subnet_routes(self, name: str, config: RangeConfig) -> None:
        """Add bidirectional routes between connected subnets through GWLB.

        Only creates routes between subnets that are connected via the
        connected_to relationship. This forces inter-subnet traffic through
        the NGFW for inspection, overriding AWS's implicit local VPC route.

        Connection is symmetric: if A lists B in connected_to OR B lists A,
        routes are created in both directions (A→B and B→A).

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration with subnets and connected_to.
        """
        if not config.gwlb_service_name:
            logger.debug("No GWLB configured, skipping inter-subnet routes")
            return

        if len(self.networks) < 2:
            logger.debug("Only one subnet, no inter-subnet routes needed")
            return

        connected_pairs = self._get_connected_pairs(config)
        if not connected_pairs:
            logger.debug("No connected subnet pairs, skipping inter-subnet routes")
            return

        route_count = 0

        for subnet_a, subnet_b in connected_pairs:
            network_a = self.networks.get(subnet_a)
            network_b = self.networks.get(subnet_b)

            if not network_a or not network_b:
                logger.warning(
                    "Skipping route pair %s<->%s: network not found",
                    subnet_a,
                    subnet_b,
                )
                continue

            # Route A → B (in A's route table, destination is B's CIDR, via GWLB)
            route_ab_name = f"{name}-{subnet_a}-to-{subnet_b}-gwlb"
            network_a.add_route_to_subnet(
                route_ab_name,
                network_b.subnet_cidr,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[
                        network_a.route_table,
                        network_a.gwlb_endpoint,
                        network_b.subnet,
                    ],
                ),
            )
            route_count += 1

            # Route B → A (in B's route table, destination is A's CIDR, via GWLB)
            route_ba_name = f"{name}-{subnet_b}-to-{subnet_a}-gwlb"
            network_b.add_route_to_subnet(
                route_ba_name,
                network_a.subnet_cidr,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[
                        network_b.route_table,
                        network_b.gwlb_endpoint,
                        network_a.subnet,
                    ],
                ),
            )
            route_count += 1

        logger.info(
            "Added %d inter-subnet routes for %d connected pairs",
            route_count,
            len(connected_pairs),
        )

        # Add blackhole routes for non-connected pairs
        self._add_blackhole_routes(name, config, connected_pairs)

    def _add_blackhole_routes(
        self,
        name: str,
        config: RangeConfig,
        connected_pairs: list[tuple[str, str]],
    ) -> None:
        """Add blackhole routes for non-connected subnet pairs.

        For subnets that are NOT in connected_to, adds routes that drop
        traffic, preventing direct communication via VPC local routing.

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration with subnets.
            connected_pairs: List of connected (subnet_a, subnet_b) tuples.
        """
        if len(self.networks) < 2:
            return

        # Build set of connected pairs for O(1) lookup
        connected_set = {frozenset(pair) for pair in connected_pairs}

        # Get all possible pairs
        subnet_names = list(self.networks.keys())
        blackhole_count = 0

        for i, subnet_a in enumerate(subnet_names):
            for subnet_b in subnet_names[i + 1 :]:
                pair_key = frozenset([subnet_a, subnet_b])
                if pair_key in connected_set:
                    continue  # Connected pair, skip

                network_a = self.networks[subnet_a]
                network_b = self.networks[subnet_b]

                # Blackhole A → B (drop traffic from A to B)
                route_ab_name = f"{name}-{subnet_a}-to-{subnet_b}-drop"
                network_a.add_blackhole_route(
                    route_ab_name,
                    network_b.subnet_cidr,
                    opts=pulumi.ResourceOptions(
                        parent=self,
                        depends_on=[network_a.route_table, network_b.subnet],
                    ),
                )
                blackhole_count += 1

                # Blackhole B → A (drop traffic from B to A)
                route_ba_name = f"{name}-{subnet_b}-to-{subnet_a}-drop"
                network_b.add_blackhole_route(
                    route_ba_name,
                    network_a.subnet_cidr,
                    opts=pulumi.ResourceOptions(
                        parent=self,
                        depends_on=[network_b.route_table, network_a.subnet],
                    ),
                )
                blackhole_count += 1

        if blackhole_count > 0:
            logger.info(
                "Added %d blackhole routes for non-connected subnet pairs",
                blackhole_count,
            )

    def _validate_config(self, config: RangeConfig) -> None:
        """Validate config has required fields for instance types present.

        Args:
            config: Range configuration to validate.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        # Check for empty subnets
        if not config.subnets:
            raise ValueError("At least one subnet is required")

        # Check for duplicate subnet names
        subnet_names = [s.name for s in config.subnets]
        if len(subnet_names) != len(set(subnet_names)):
            raise ValueError("Subnet names must be unique")

        # Check DC requirements by iterating through subnets
        has_dc = any(inst.role == "dc" for subnet in config.subnets for inst in subnet.instances)
        if has_dc and not config.dc_ami_id:
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

    def get_outputs(self) -> dict[str, object]:
        """Get all outputs for export to the main Pulumi program.

        Returns:
            Dictionary with all range outputs including subnets and instances.
        """
        # Build subnets output dict
        subnets_output: dict[str, dict[str, pulumi.Output[str]]] = {
            name: {
                "subnet_id": net.subnet_id,
                "subnet_cidr": net.subnet_cidr,
                "security_group_id": net.security_group_id,
                "route_table_id": net.route_table_id,
                "gwlb_endpoint_id": net.gwlb_endpoint_id,
            }
            for name, net in self.networks.items()
        }

        # Build instance outputs with subnet_name
        instance_outputs = [self._build_instance_output(inst, subnet_name) for inst, subnet_name in self.instances]

        return {
            "subnets": subnets_output,
            "instances": instance_outputs,
            "dc_config_param_name": self.dc_config_param_name,
        }
