"""Range stack component for Shifter range provisioning.

This is the main composition component that brings together:
- Networks (multiple subnets with SG, RT per subnet)
- Instances (Kali, victims, DC) placed in their designated subnets

DC instances are created first to ensure domain controllers are available
before domain member instances that depend on them.

Inter-subnet traffic (for connected subnets) is routed through the NGFW
data ENI for inspection. Non-connected subnets have blackhole routes.

NGFW configuration (routes, addresses, security rules) is done after subnet
creation but before instance setup, ensuring traffic can flow before instances
try to communicate (e.g., domain join).
"""

import asyncio
import ipaddress
import logging
import time
from collections.abc import Awaitable
from typing import Any, cast

import pulumi

from components.instance import InstanceComponent
from components.network import NetworkComponent, allocate_subnets
from config import InstanceConfig, RangeConfig
from executors.ngfw_executor import NGFWExecutor
from main import poll_for_serial_number
from plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan

logger = logging.getLogger(__name__)


class RangeStack(pulumi.ComponentResource):
    """Creates a complete range with all infrastructure.

    This is the main entry point for provisioning a range. It composes:
    - NetworkComponent(s) for each logical subnet (with SG, RT per subnet)
    - InstanceComponent(s) for each configured instance, placed in designated subnets

    DC instances are created first (dependency ordering) to ensure the domain
    controller is available before domain members attempt to join.

    Inter-subnet traffic between connected subnets is routed through the NGFW
    data ENI for inspection. Non-connected subnets have blackhole routes.

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
        self._create_all_instances(name, config)
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
            "name": instance.display_name,
            "role": instance.role,
            "os": instance.os_type,
            "subnet_name": subnet_name,
            "instance_id": instance.instance_id,
            "private_ip": instance.private_ip,
            "ssh_key_secret_arn": instance.ssh_key_secret_arn,
            "public_key": instance.public_key or "",
            "agent_presigned_url": instance.agent_presigned_url or "",
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

    def _configure_ngfw(self, config: RangeConfig) -> None:
        """Configure NGFW with routes, addresses, and security rules.

        Runs AFTER subnets are created but BEFORE instances are created.
        This ensures NGFW routing is in place when instances try to
        communicate (e.g., domain join).

        Uses asyncio.to_thread to run blocking SSH operations without
        blocking Pulumi's event loop.

        Args:
            config: Range configuration with NGFW connection info.
        """
        if not config.ngfw_management_ip:
            logger.debug("No NGFW configured, skipping NGFW configuration")
            return

        if not config.ngfw_ssh_key_secret_arn:
            logger.warning("NGFW missing SSH key ARN, skipping configuration")
            return

        if not config.ngfw_subnet_cidr:
            raise ValueError("ngfw_subnet_cidr required when ngfw_management_ip is set")

        # Build subnet info for NGFW configuration
        subnets_for_ngfw = []
        for subnet_name, network in self.networks.items():
            # Find the subnet config to get connected_to
            subnet_config = next((s for s in config.subnets if s.name == subnet_name), None)
            connected_to = subnet_config.connected_to if subnet_config else []

            # subnet_cidr is a Pulumi Output - we need to resolve it
            # We use apply() to schedule the NGFW config after CIDRs are known
            subnets_for_ngfw.append(
                {
                    "name": subnet_name,
                    "cidr_output": network.subnet_cidr,
                    "connected_to": connected_to,
                }
            )

        # Schedule NGFW configuration after all subnet CIDRs are resolved
        cidr_outputs = [s["cidr_output"] for s in subnets_for_ngfw]

        def do_ngfw_config(cidrs: list[str]) -> bool:
            """Execute NGFW configuration (blocking, runs in thread)."""
            # Build final subnet list with resolved CIDRs
            subnets = []
            for i, subnet_info in enumerate(subnets_for_ngfw):
                subnets.append(
                    {
                        "name": subnet_info["name"],
                        "cidr": cidrs[i],
                        "connected_to": subnet_info["connected_to"],
                    }
                )

            self._execute_ngfw_config(
                subnets=subnets,
                range_id=config.range_id,
                management_ip=config.ngfw_management_ip,
                ssh_key_secret_arn=config.ngfw_ssh_key_secret_arn,
                ngfw_subnet_cidr=config.ngfw_subnet_cidr,
            )
            return True

        def schedule_ngfw_config(cidrs: list[str]) -> Awaitable[bool]:
            """Schedule blocking NGFW config on a thread."""
            return asyncio.to_thread(do_ngfw_config, cidrs)

        # Store result to ensure Pulumi waits for completion
        self.ngfw_config_result: pulumi.Output[bool] = pulumi.Output.all(*cidr_outputs).apply(schedule_ngfw_config)

    def _execute_ngfw_config(
        self,
        subnets: list[dict],
        range_id: int,
        management_ip: str,
        ssh_key_secret_arn: str,
        ngfw_subnet_cidr: str,
    ) -> None:
        """Execute NGFW configuration via SSH (blocking).

        This is the actual SSH work - runs on a separate thread.

        Args:
            subnets: List of dicts with 'name', 'cidr', 'connected_to'.
            range_id: Range ID for unique naming.
            management_ip: NGFW management IP for SSH.
            ssh_key_secret_arn: Secrets Manager ARN for SSH private key.
            ngfw_subnet_cidr: NGFW subnet CIDR for computing gateway IP.
        """
        # Compute VPC gateway IP (first IP + 1 in the subnet)
        network = ipaddress.ip_network(ngfw_subnet_cidr, strict=False)
        vpc_gateway_ip = str(network.network_address + 1)
        logger.info(
            "Configuring NGFW: %d subnets, gateway=%s",
            len(subnets),
            vpc_gateway_ip,
        )

        # Get SSH private key from Secrets Manager
        from cloud import get_secrets_store

        secrets = get_secrets_store()
        private_key = secrets.get_secret(ssh_key_secret_arn)

        # Create NGFW executor
        ssh_executor = NGFWExecutor(private_key=private_key)

        # Wait for SSH to be available
        logger.info("Waiting for SSH on NGFW at %s...", management_ip)
        ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

        # Wait for management plane to be ready (especially important after NGFW start)
        logger.info("Verifying NGFW management plane is ready...")
        poll_for_serial_number(
            ssh_executor=ssh_executor,
            host=management_ip,
            timeout_seconds=300,
            poll_interval=15,
        )

        # Build and execute the configure plan
        plan = NGFWConfigureSubnetsPlan()
        steps = plan.get_steps(subnets, range_id, vpc_gateway_ip)

        # Execute steps with retry logic
        for step in steps:
            logger.info("Executing NGFW config step: %s", step.name)
            result = None
            for attempt in range(5):
                if attempt > 0:
                    logger.info("Retry %d/4 for step %s", attempt, step.name)
                    time.sleep(15)
                result = ssh_executor.run_command(
                    instance_id=management_ip,
                    script=step.script,
                    stdin_input=step.stdin_input,
                    timeout_seconds=step.timeout_seconds,
                )
                # Debug logging for NGFW command output
                logger.info(
                    "NGFW step '%s' attempt %d: success=%s, exit_code=%s, stdout=%d bytes, stderr=%d bytes",
                    step.name,
                    attempt + 1,
                    result.success,
                    result.exit_code,
                    len(result.stdout) if result.stdout else 0,
                    len(result.stderr) if result.stderr else 0,
                )
                if result.stdout:
                    logger.info("NGFW stdout (first 1000 chars):\n%s", result.stdout[:1000])
                if result.stderr:
                    logger.info("NGFW stderr (first 500 chars):\n%s", result.stderr[:500])

                if result.success and self._check_commit_success(result.stdout):
                    break
                if result.success and not self._check_commit_success(result.stdout):
                    logger.warning(
                        "NGFW step '%s' SSH OK but commit failed: %s",
                        step.name,
                        result.stdout[:500] if result.stdout else "(empty)",
                    )
            if not result or not result.success:
                stderr = result.stderr if result else "no result"
                raise RuntimeError(f"NGFW config step '{step.name}' failed: {stderr}")
            if not self._check_commit_success(result.stdout):
                raise RuntimeError(
                    f"NGFW step '{step.name}' commit failed after retries: "
                    f"{result.stdout[:500] if result.stdout else '(empty)'}"
                )
            logger.info("NGFW config step '%s' completed", step.name)

        logger.info(
            "NGFW configuration complete for range %s (%d subnets)",
            range_id,
            len(subnets),
        )

    def _check_commit_success(self, output: str) -> bool:
        """Check if PAN-OS commit succeeded.

        PAN-OS outputs "Configuration committed successfully" on successful commits.
        If there are no changes to commit, PAN-OS outputs "There are no changes to commit"
        which is also considered success (idempotent behavior).

        Args:
            output: Command output to check.

        Returns:
            True if no commit was attempted or commit succeeded.
        """
        # Debug logging to diagnose commit output issues
        logger.debug("Commit check - output length: %d bytes", len(output) if output else 0)
        logger.debug("Commit check - raw output:\n%s", output[:2000] if output else "(empty)")

        if not output:
            logger.debug("Commit check - no output, assuming success")
            return True
        if "commit" not in output.lower():
            logger.debug("Commit check - no 'commit' in output, assuming success")
            return True

        # Check for success messages
        if "Configuration committed successfully" in output:
            logger.debug("Commit check - found 'Configuration committed successfully'")
            return True
        if "There are no changes to commit" in output:
            logger.debug("Commit check - found 'There are no changes to commit' (idempotent)")
            return True

        logger.debug("Commit check - no success message found, commit failed")
        return False

    def _run_all_setup(self, dc_components: list[InstanceComponent], config: RangeConfig) -> None:
        """Run setup for all instances (DCs first, then others in parallel).

        DC setup must complete before domain-joining victims attempt to join.
        Domain-joining instances run their setups in parallel using threading.

        Args:
            dc_components: List of DC instance components.
            config: Range configuration.
        """
        # Run DC setup FIRST - must complete before victims can domain join
        for dc_instance in dc_components:
            dc_instance.run_dc_setup()

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

        # Separate domain-joining and non-domain-joining instances
        domain_join_instances: list[InstanceComponent] = []
        non_domain_join_instances: list[InstanceComponent] = []

        for inst_config, instance in non_dc_pairs:
            if inst_config.join_domain and dc_components:
                domain_join_instances.append(instance)
            else:
                non_domain_join_instances.append(instance)

        # Run non-domain-joining instances immediately (they don't need DC)
        for instance in non_domain_join_instances:
            instance.run_setup()

        # Run domain-joining instances in parallel after DC is ready
        # All run_setup() calls are kicked off in the same apply callback.
        # Since run_setup() returns a Pulumi Output (non-blocking), Pulumi
        # executes the underlying Commands in parallel.
        if domain_join_instances and dc_components:
            dc_domain = cast(str, dc_components[0].domain_name)
            dc_setup_result = dc_components[0].setup_result

            if dc_setup_result is not None:

                def run_all_domain_joins(
                    args: list[Any],
                    instances: list[InstanceComponent] = domain_join_instances,
                    domain: str = dc_domain,
                ) -> None:
                    """Kick off all domain join setups (Pulumi runs them in parallel)."""
                    _dc_ready, dc_ip = args[0], args[1]
                    for inst in instances:
                        inst.run_setup(dc_ip=dc_ip, domain_name=domain)

                # Wait for both DC setup and DC IP, then run all domain joins
                pulumi.Output.all(dc_setup_result, dc_components[0].private_ip).apply(run_all_domain_joins)
            else:
                # DC setup not triggered yet - fall back to IP-only dependency
                def run_all_domain_joins_with_ip(
                    dc_ip: str,
                    instances: list[InstanceComponent] = domain_join_instances,
                    domain: str = dc_domain,
                ) -> None:
                    """Kick off all domain join setups (Pulumi runs them in parallel)."""
                    for inst in instances:
                        inst.run_setup(dc_ip=dc_ip, domain_name=domain)

                dc_components[0].private_ip.apply(run_all_domain_joins_with_ip)

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
            "display_name": inst_config.name,
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
        security group and route table.

        Pre-allocates all subnet CIDRs atomically before creating any
        NetworkComponent to prevent race conditions where multiple subnets
        get the same CIDR.

        After all networks are created, adds inter-subnet routes to force
        connected subnet traffic through the NGFW data ENI.

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
        # This holds the advisory lock for the entire allocation and reserves
        # CIDRs in the allocation table to prevent TOCTOU races
        allocated_cidrs = allocate_subnets(
            vpc_id=config.vpc_id,
            cidr_prefix=cidr_prefix,
            count=subnet_count,
            subnet_size=28,  # All range subnets use /28
            range_id=config.range_id,
            request_id=config.request_uuid,
        )

        logger.info(
            "Pre-allocated %d CIDRs: %s",
            len(allocated_cidrs),
            allocated_cidrs,
        )

        # Build name→CIDR map for connected subnet lookups
        if len(config.subnets) != len(allocated_cidrs):
            raise ValueError(
                f"Subnet count mismatch: {len(config.subnets)} subnets but {len(allocated_cidrs)} CIDRs allocated"
            )
        name_to_cidr: dict[str, str] = {subnet.name: allocated_cidrs[idx] for idx, subnet in enumerate(config.subnets)}
        logger.debug("Built name→CIDR map: %s", name_to_cidr)

        # Compute connected pairs once, reuse for SG rules and routes
        connected_pairs = self._get_connected_pairs(config)
        logger.debug(
            "Computed %d connected pairs: %s",
            len(connected_pairs),
            connected_pairs,
        )

        for idx, subnet_config in enumerate(config.subnets):
            network_name = f"{name}-net-{subnet_config.name}"
            subnet_cidr = allocated_cidrs[idx]

            # Get CIDRs of connected subnets for SG ingress rules
            connected_cidrs = self._get_connected_cidrs(
                subnet_config.name,
                connected_pairs,
                name_to_cidr,
            )

            logger.debug(
                "Creating network %s (uuid=%s, cidr=%s, ngfw=%s, connected_cidrs=%s)",
                network_name,
                subnet_config.uuid,
                subnet_cidr,
                "enabled" if config.ngfw_data_eni_id else "disabled",
                connected_cidrs,
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
                s3_endpoint_id=config.s3_endpoint_id,
                firewall_endpoint_id=config.firewall_endpoint_id,
                portal_vpc_cidr=config.portal_vpc_cidr,
                portal_vpc_peering_id=config.portal_vpc_peering_id,
                allocated_cidr=subnet_cidr,
                connected_subnet_cidrs=connected_cidrs,
                opts=pulumi.ResourceOptions(parent=self),
            )
            self.networks[subnet_config.name] = network

        # Add inter-subnet routes to force connected traffic through NGFW
        self._add_inter_subnet_routes(name, config, connected_pairs)

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

    def _get_connected_cidrs(
        self,
        subnet_name: str,
        connected_pairs: list[tuple[str, str]],
        name_to_cidr: dict[str, str],
    ) -> list[str]:
        """Get CIDRs of subnets connected to a given subnet.

        Looks up which subnets are connected to the given subnet from the
        pre-computed pairs, then resolves their names to CIDRs.

        Args:
            subnet_name: The subnet to find connections for.
            connected_pairs: List of (subnet_a, subnet_b) connected pairs.
            name_to_cidr: Mapping of subnet name to allocated CIDR.

        Returns:
            List of CIDRs for connected subnets. Empty if no connections.

        Raises:
            KeyError: If a connected subnet name is not in name_to_cidr map.
        """
        connected_cidrs: list[str] = []

        for subnet_a, subnet_b in connected_pairs:
            if subnet_a == subnet_name:
                peer_name = subnet_b
            elif subnet_b == subnet_name:
                peer_name = subnet_a
            else:
                continue

            if peer_name not in name_to_cidr:
                raise KeyError(
                    f"Connected subnet '{peer_name}' not found in CIDR map. "
                    f"Available subnets: {list(name_to_cidr.keys())}"
                )
            connected_cidrs.append(name_to_cidr[peer_name])

        logger.debug(
            "Subnet '%s' connected to CIDRs: %s",
            subnet_name,
            connected_cidrs,
        )
        return connected_cidrs

    def _add_inter_subnet_routes(
        self,
        name: str,
        config: RangeConfig,
        connected_pairs: list[tuple[str, str]],
    ) -> None:
        """Add bidirectional routes between ALL subnets through NGFW.

        Routes ALL inter-subnet traffic through the NGFW data ENI for inspection,
        overriding AWS's implicit local VPC routing. The NGFW security policy
        controls which traffic is allowed vs denied.

        The connected_pairs parameter is kept for API compatibility but is no
        longer used - all subnet pairs get routes through NGFW.

        Args:
            name: Pulumi resource name prefix.
            config: Range configuration with subnets.
            connected_pairs: Unused, kept for API compatibility.
        """
        if not config.ngfw_data_eni_id:
            logger.debug("No NGFW configured, skipping inter-subnet routes")
            return

        if len(self.networks) < 2:
            logger.debug("Only one subnet, no inter-subnet routes needed")
            return

        # Build all subnet pairs
        subnet_names = list(self.networks.keys())
        route_count = 0

        for i, subnet_a in enumerate(subnet_names):
            for subnet_b in subnet_names[i + 1 :]:
                network_a = self.networks[subnet_a]
                network_b = self.networks[subnet_b]

                # Route A → B (in A's route table, destination is B's CIDR, via NGFW)
                route_ab_name = f"{name}-{subnet_a}-to-{subnet_b}-ngfw"
                network_a.add_route_to_ngfw(
                    route_ab_name,
                    network_b.subnet_cidr,
                    config.ngfw_data_eni_id,
                    opts=pulumi.ResourceOptions(
                        parent=self,
                        depends_on=[
                            network_a.route_table,
                            network_b.subnet,
                        ],
                    ),
                )
                route_count += 1

                # Route B → A (in B's route table, destination is A's CIDR, via NGFW)
                route_ba_name = f"{name}-{subnet_b}-to-{subnet_a}-ngfw"
                network_b.add_route_to_ngfw(
                    route_ba_name,
                    network_a.subnet_cidr,
                    config.ngfw_data_eni_id,
                    opts=pulumi.ResourceOptions(
                        parent=self,
                        depends_on=[
                            network_b.route_table,
                            network_a.subnet,
                        ],
                    ),
                )
                route_count += 1

        # Route traffic to SSM/Bedrock endpoints subnet through NGFW
        # This overrides the implicit local VPC route for the endpoints subnet CIDR,
        # forcing Bedrock (and SSM/STS) traffic through NGFW for inspection/logging
        if config.ssm_endpoints_subnet_cidr:
            for subnet_name in subnet_names:
                network = self.networks[subnet_name]
                route_name = f"{name}-{subnet_name}-to-endpoints-ngfw"
                network.add_route_to_ngfw(
                    route_name,
                    pulumi.Output.from_input(config.ssm_endpoints_subnet_cidr),
                    config.ngfw_data_eni_id,
                    opts=pulumi.ResourceOptions(
                        parent=self,
                        depends_on=[network.route_table],
                    ),
                )
                route_count += 1
            logger.info(
                "Added %d endpoint subnet routes through NGFW",
                len(subnet_names),
            )

        logger.info(
            "Added %d total routes through NGFW for %d subnets",
            route_count,
            len(subnet_names),
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
