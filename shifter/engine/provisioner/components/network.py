"""Network component for Shifter range provisioning.

This component creates the network infrastructure for a logical subnet:
- AWS Subnet (/28 for logical subnets, /24 for legacy single-subnet)
- Security Group (intra-subnet unrestricted, GWLB return traffic)
- Route Table (0.0.0.0/0 → GWLB endpoint for internet traffic)
- GWLB Endpoint (when NGFW is enabled)

Inter-subnet routing:
After NetworkComponents are created, RangeStack adds explicit routes from
each subnet to every other subnet's CIDR via the GWLB. This overrides AWS's
implicit local VPC route, forcing ALL inter-subnet traffic through the NGFW.
Without these routes, traffic between 10.1.2.0/28 and 10.1.3.0/28 would use
the local route and bypass NGFW inspection entirely.
"""

import ipaddress
import logging
import os

import boto3
import pulumi
import pulumi_aws as aws

logger = logging.getLogger(__name__)


def _publish_subnet_exhaustion_alarm(vpc_id: str, cidr_prefix: str, subnet_size: int) -> None:
    """Publish a CloudWatch metric and log for subnet exhaustion.

    This is a critical infrastructure alert - if we run out of subnets,
    users cannot launch ranges. The metric triggers a CloudWatch alarm
    that sends an email notification.

    Args:
        vpc_id: The VPC that has no free subnets.
        cidr_prefix: The CIDR prefix that was searched.
        subnet_size: The subnet size that was requested (e.g., 24 or 28).
    """
    region = os.environ.get("AWS_REGION", "us-east-2")
    cloudwatch = boto3.client("cloudwatch", region_name=region)

    # Publish metric for CloudWatch alarm
    cloudwatch.put_metric_data(
        Namespace="Shifter/RangeProvisioning",
        MetricData=[
            {
                "MetricName": "SubnetExhaustion",
                "Value": 1,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "VpcId", "Value": vpc_id},
                    {"Name": "SubnetSize", "Value": str(subnet_size)},
                ],
            }
        ],
    )

    # Log with distinctive pattern for metric filter
    logger.error(
        "CRITICAL: Subnet exhaustion in VPC %s. "
        "No free /%d subnet available in prefix %s. "
        "This is user-impacting - investigate immediately.",
        vpc_id,
        subnet_size,
        cidr_prefix,
    )
    pulumi.log.error(
        f"CRITICAL: Subnet exhaustion in VPC {vpc_id}. "
        f"No free /{subnet_size} subnet available in prefix {cidr_prefix}. "
        "This is user-impacting - investigate immediately."
    )


def _get_existing_subnets(vpc_id: str) -> list[ipaddress.IPv4Network]:
    """Query AWS for all existing subnets in a VPC.

    Args:
        vpc_id: The VPC ID to check.

    Returns:
        List of existing subnet networks.
    """
    ec2 = boto3.client("ec2")
    response = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])

    existing_networks: list[ipaddress.IPv4Network] = []
    for subnet in response.get("Subnets", []):
        try:
            network = ipaddress.ip_network(subnet["CidrBlock"])
            if isinstance(network, ipaddress.IPv4Network):
                existing_networks.append(network)
        except ValueError:
            logger.warning("Invalid CIDR in AWS response: %s", subnet.get("CidrBlock"))
            continue

    logger.debug("Found %d existing subnets in VPC %s", len(existing_networks), vpc_id)
    return existing_networks


def _find_free_subnet(vpc_id: str, cidr_prefix: str, subnet_size: int = 24) -> str:
    """Find a free subnet in the VPC by querying AWS.

    This queries AWS for all existing subnets in the VPC and finds a subnet
    of the requested size that doesn't conflict with any of them.

    For /24 subnets: iterates through third octet (10.1.2.0/24, 10.1.3.0/24, ...)
    For /28 subnets: iterates through all /28 blocks (10.1.2.0/28, 10.1.2.16/28, ...)

    Args:
        vpc_id: The VPC ID to check.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        subnet_size: The subnet prefix length (24 or 28). Default 24.

    Returns:
        A free CIDR block (e.g., "10.1.8.0/24" or "10.1.2.16/28").

    Raises:
        RuntimeError: If no free subnet can be found.
        ValueError: If subnet_size is not 24 or 28.
    """
    if subnet_size not in (24, 28):
        raise ValueError(f"subnet_size must be 24 or 28, got {subnet_size}")

    logger.info(
        "Finding free /%d subnet in VPC %s with prefix %s",
        subnet_size,
        vpc_id,
        cidr_prefix,
    )

    existing_networks = _get_existing_subnets(vpc_id)
    pulumi.log.info(f"Found {len(existing_networks)} existing subnets in VPC {vpc_id}")

    # Generate candidate CIDRs based on subnet size
    if subnet_size == 24:
        # /24 subnets: 10.1.2.0/24 through 10.1.254.0/24
        # Reserve .0.x and .1.x for infrastructure
        candidates = _generate_slash24_candidates(cidr_prefix)
    else:
        # /28 subnets: iterate all /28 blocks starting from .2.0
        candidates = _generate_slash28_candidates(cidr_prefix)

    # Find first non-overlapping candidate
    for candidate_cidr in candidates:
        candidate_network = ipaddress.ip_network(candidate_cidr)

        has_conflict = any(candidate_network.overlaps(existing) for existing in existing_networks)

        if not has_conflict:
            logger.info("Found free subnet: %s", candidate_cidr)
            pulumi.log.info(f"Found free subnet: {candidate_cidr}")
            return candidate_cidr

    # No free subnet found - critical infrastructure issue
    _publish_subnet_exhaustion_alarm(vpc_id, cidr_prefix, subnet_size)

    raise RuntimeError(
        f"No free /{subnet_size} subnet available in VPC {vpc_id}. "
        f"All subnets in prefix {cidr_prefix} are in use or conflict with existing subnets."
    )


def _generate_slash24_candidates(cidr_prefix: str) -> list[str]:
    """Generate candidate /24 CIDRs.

    Args:
        cidr_prefix: The first two octets (e.g., "10.1").

    Returns:
        List of candidate CIDR strings (e.g., ["10.1.2.0/24", "10.1.3.0/24", ...]).
    """
    # Range: 10.1.2.0/24 through 10.1.254.0/24 (253 possible subnets)
    # Reserve .0 and .1 for infrastructure
    return [f"{cidr_prefix}.{third_octet}.0/24" for third_octet in range(2, 255)]


def _generate_slash28_candidates(cidr_prefix: str) -> list[str]:
    """Generate candidate /28 CIDRs.

    /28 = 16 IPs per subnet, so fourth octet starts at 0, 16, 32, ..., 240.
    We skip .0.x and .1.x for infrastructure, starting at .2.0/28.

    Args:
        cidr_prefix: The first two octets (e.g., "10.1").

    Returns:
        List of candidate CIDR strings (e.g., ["10.1.2.0/28", "10.1.2.16/28", ...]).
    """
    candidates: list[str] = []

    # Third octet: 2-254 (skip .0 and .1 for infrastructure)
    for third_octet in range(2, 255):
        # Fourth octet: 0, 16, 32, 48, ..., 240 (16 /28 blocks per /24)
        for fourth_octet in range(0, 256, 16):
            candidates.append(f"{cidr_prefix}.{third_octet}.{fourth_octet}/28")

    return candidates


class NetworkComponent(pulumi.ComponentResource):
    """Creates network infrastructure for a logical subnet.

    Creates per-subnet resources:
    - AWS Subnet (/28 for logical subnets, /24 for legacy)
    - Security Group (intra-subnet unrestricted, VPC CIDR for GWLB return)
    - Route Table (0.0.0.0/0 → GWLB endpoint when NGFW enabled)
    - GWLB Endpoint (when gwlb_service_name provided)

    Attributes:
        subnet: The created subnet resource.
        subnet_id: The subnet ID.
        subnet_cidr: The CIDR block of the subnet.
        security_group: The created security group.
        security_group_id: The security group ID.
        route_table: The created route table.
        route_table_id: The route table ID.
        gwlb_endpoint: The GWLB endpoint (None if no NGFW).
        gwlb_endpoint_id: The GWLB endpoint ID (empty string if no NGFW).
    """

    subnet: aws.ec2.Subnet
    subnet_id: pulumi.Output[str]
    subnet_cidr: pulumi.Output[str]
    security_group: aws.ec2.SecurityGroup
    security_group_id: pulumi.Output[str]
    route_table: aws.ec2.RouteTable
    route_table_id: pulumi.Output[str]
    gwlb_endpoint: aws.ec2.VpcEndpoint | None
    gwlb_endpoint_id: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        range_id: int,
        user_id: int,
        vpc_id: str,
        vpc_cidr: str,
        cidr_prefix: str,
        environment: str,
        availability_zone: str,
        subnet_name: str = "",
        subnet_uuid: str = "",
        request_uuid: str = "",
        subnet_size: int = 24,
        gwlb_service_name: str = "",
        opts: pulumi.ResourceOptions | None = None,
    ):
        """Create network infrastructure for a logical subnet.

        Args:
            name: Pulumi resource name prefix.
            range_id: The range ID.
            user_id: The user ID who owns this range.
            vpc_id: The VPC ID to create the subnet in.
            vpc_cidr: The VPC CIDR block (e.g., "10.1.0.0/16") for SG rules.
            cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
            environment: Environment name (dev/prod).
            availability_zone: The AZ to create the subnet in (e.g., "us-east-2a").
            subnet_name: Logical subnet name (e.g., "attack", "target").
            subnet_uuid: Logical subnet UUID for tagging.
            request_uuid: Request UUID for correlation.
            subnet_size: Subnet prefix length (24 or 28). Default 24.
            gwlb_service_name: GWLB VPC Endpoint Service name. Empty = no NGFW.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NetworkComponent", name, None, opts)

        logger.info(
            "Creating NetworkComponent: name=%s, subnet_name=%s, size=/%d, gwlb=%s",
            name,
            subnet_name,
            subnet_size,
            "enabled" if gwlb_service_name else "disabled",
        )

        # Find a free subnet by querying AWS directly
        allocated_cidr = _find_free_subnet(vpc_id, cidr_prefix, subnet_size)

        # Build common tags for all resources
        common_tags = self._build_common_tags(
            range_id=range_id,
            user_id=user_id,
            environment=environment,
            subnet_name=subnet_name,
            subnet_uuid=subnet_uuid,
            request_uuid=request_uuid,
        )

        # Create subnet
        self._create_subnet(name, vpc_id, allocated_cidr, availability_zone, common_tags)

        # Create security group for this subnet
        self._create_security_group(name, vpc_id, vpc_cidr, allocated_cidr, common_tags)

        # Create route table for this subnet
        self._create_route_table(name, vpc_id, common_tags)

        # Create GWLB endpoint if service name provided
        self._create_gwlb_endpoint(name, vpc_id, gwlb_service_name, common_tags)

        # Associate route table with subnet
        aws.ec2.RouteTableAssociation(
            f"{name}-rta",
            subnet_id=self.subnet.id,
            route_table_id=self.route_table.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self._register_outputs()

    def _build_common_tags(
        self,
        range_id: int,
        user_id: int,
        environment: str,
        subnet_name: str,
        subnet_uuid: str,
        request_uuid: str,
    ) -> dict[str, str]:
        """Build common tags for all resources.

        Args:
            range_id: The range ID.
            user_id: The user ID.
            environment: Environment name.
            subnet_name: Logical subnet name.
            subnet_uuid: Logical subnet UUID.
            request_uuid: Request UUID.

        Returns:
            Dict of tag key-value pairs.
        """
        tags = {
            "shifter:range_id": str(range_id),
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "shifter:system": "shifter",
            "ManagedBy": "pulumi",
        }

        # Add optional tags if provided
        if subnet_name:
            tags["shifter:subnet_name"] = subnet_name
        if subnet_uuid:
            tags["shifter:subnet_uuid"] = subnet_uuid
        if request_uuid:
            tags["shifter:request_uuid"] = request_uuid

        return tags

    def _create_subnet(
        self,
        name: str,
        vpc_id: str,
        cidr_block: str,
        availability_zone: str,
        common_tags: dict[str, str],
    ) -> None:
        """Create the AWS subnet.

        Args:
            name: Resource name prefix.
            vpc_id: VPC ID.
            cidr_block: Allocated CIDR block.
            availability_zone: Availability zone.
            common_tags: Common tags dict.
        """
        subnet_name_tag = common_tags.get("shifter:subnet_name", "")
        user_id = common_tags.get("shifter:user_id", "")

        # Name format: shifter-{subnet_name}-{user_id} or shifter-range-{range_id}
        if subnet_name_tag:
            display_name = f"shifter-{subnet_name_tag}-{user_id}"
        else:
            display_name = f"shifter-range-{common_tags.get('shifter:range_id', '')}"

        self.subnet = aws.ec2.Subnet(
            f"{name}-subnet",
            vpc_id=vpc_id,
            cidr_block=cidr_block,
            availability_zone=availability_zone,
            tags={
                **common_tags,
                "Name": display_name,
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.subnet_id = self.subnet.id
        # Map to ensure non-None (we always provide cidr_block so it's never None)
        self.subnet_cidr = self.subnet.cidr_block.apply(lambda c: c or "")

        logger.debug("Created subnet %s with CIDR %s", name, cidr_block)

    def _create_security_group(
        self,
        name: str,
        vpc_id: str,
        vpc_cidr: str,
        subnet_cidr: str,
        common_tags: dict[str, str],
    ) -> None:
        """Create security group for this subnet.

        Rules:
        - Inbound: Allow ALL from same subnet CIDR (intra-subnet unrestricted)
        - Inbound: Allow ALL from VPC CIDR (for GWLB return traffic)
        - Outbound: Allow ALL

        Args:
            name: Resource name prefix.
            vpc_id: VPC ID.
            vpc_cidr: VPC CIDR block for return traffic rule.
            subnet_cidr: This subnet's CIDR block.
            common_tags: Common tags dict.
        """
        subnet_name_tag = common_tags.get("shifter:subnet_name", "default")

        self.security_group = aws.ec2.SecurityGroup(
            f"{name}-sg",
            vpc_id=vpc_id,
            description=f"Security group for {subnet_name_tag} subnet",
            ingress=[
                # Allow all intra-subnet traffic
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=[subnet_cidr],
                    description="Allow all intra-subnet traffic",
                ),
                # Allow all from VPC (GWLB return traffic)
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=[vpc_cidr],
                    description="Allow GWLB return traffic from VPC",
                ),
            ],
            egress=[
                # Allow all outbound
                aws.ec2.SecurityGroupEgressArgs(
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=["0.0.0.0/0"],
                    description="Allow all outbound traffic",
                ),
            ],
            tags={
                **common_tags,
                "Name": f"shifter-{subnet_name_tag}-sg",
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.security_group_id = self.security_group.id

        logger.debug("Created security group for subnet %s", name)

    def _create_route_table(
        self,
        name: str,
        vpc_id: str,
        common_tags: dict[str, str],
    ) -> None:
        """Create route table for this subnet.

        The route table starts with just the local VPC route (implicit).
        GWLB route is added separately if NGFW is enabled.

        Args:
            name: Resource name prefix.
            vpc_id: VPC ID.
            common_tags: Common tags dict.
        """
        subnet_name_tag = common_tags.get("shifter:subnet_name", "default")

        self.route_table = aws.ec2.RouteTable(
            f"{name}-rt",
            vpc_id=vpc_id,
            tags={
                **common_tags,
                "Name": f"shifter-{subnet_name_tag}-rt",
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.route_table_id = self.route_table.id

        logger.debug("Created route table for subnet %s", name)

    def _create_gwlb_endpoint(
        self,
        name: str,
        vpc_id: str,
        gwlb_service_name: str,
        common_tags: dict[str, str],
    ) -> None:
        """Create GWLB endpoint if service name provided.

        When NGFW is enabled, creates a VPC endpoint for the GWLB and adds
        a default route (0.0.0.0/0) to the route table pointing to it.

        Args:
            name: Resource name prefix.
            vpc_id: VPC ID.
            gwlb_service_name: GWLB VPC Endpoint Service name. Empty = no NGFW.
            common_tags: Common tags dict.
        """
        if not gwlb_service_name:
            self.gwlb_endpoint = None
            self.gwlb_endpoint_id = pulumi.Output.from_input("")
            logger.debug("No GWLB service name provided, skipping endpoint creation")
            return

        subnet_name_tag = common_tags.get("shifter:subnet_name", "default")

        logger.info(
            "Creating GWLB endpoint for subnet %s with service %s",
            name,
            gwlb_service_name,
        )

        # Create VPC endpoint for GWLB
        self.gwlb_endpoint = aws.ec2.VpcEndpoint(
            f"{name}-gwlbe",
            vpc_id=vpc_id,
            service_name=gwlb_service_name,
            vpc_endpoint_type="GatewayLoadBalancer",
            subnet_ids=[self.subnet.id],
            tags={
                **common_tags,
                "Name": f"shifter-{subnet_name_tag}-gwlbe",
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.subnet]),
        )

        self.gwlb_endpoint_id = self.gwlb_endpoint.id

        # Add default route to GWLB endpoint for inter-subnet traffic
        aws.ec2.Route(
            f"{name}-gwlb-route",
            route_table_id=self.route_table.id,
            destination_cidr_block="0.0.0.0/0",
            vpc_endpoint_id=self.gwlb_endpoint.id,
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[self.route_table, self.gwlb_endpoint],
            ),
        )

        logger.info("Created GWLB endpoint and default route for subnet %s", name)

    def add_route_to_subnet(
        self,
        name: str,
        destination_cidr: pulumi.Output[str],
        opts: pulumi.ResourceOptions | None = None,
    ) -> aws.ec2.Route | None:
        """Add a route to another subnet's CIDR through GWLB.

        This overrides AWS's implicit local VPC route for that specific CIDR,
        forcing traffic through the GWLB/NGFW instead of direct local routing.

        Use this after all NetworkComponents are created to add inter-subnet
        routes that force all inter-subnet traffic through the NGFW.

        Args:
            name: Unique resource name for this route.
            destination_cidr: The destination subnet's CIDR block (Pulumi Output).
            opts: Optional Pulumi resource options.

        Returns:
            The created Route resource, or None if no GWLB endpoint.
        """
        if not self.gwlb_endpoint:
            logger.debug(
                "No GWLB endpoint, skipping inter-subnet route %s",
                name,
            )
            return None

        logger.debug("Adding inter-subnet route %s", name)

        return aws.ec2.Route(
            name,
            route_table_id=self.route_table.id,
            destination_cidr_block=destination_cidr,
            vpc_endpoint_id=self.gwlb_endpoint.id,
            opts=opts or pulumi.ResourceOptions(parent=self),
        )

    def _register_outputs(self) -> None:
        """Register Pulumi outputs."""
        self.register_outputs(
            {
                "subnetId": self.subnet_id,
                "subnetCidr": self.subnet_cidr,
                "securityGroupId": self.security_group_id,
                "routeTableId": self.route_table_id,
                "gwlbEndpointId": self.gwlb_endpoint_id,
            }
        )
