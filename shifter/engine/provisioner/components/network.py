"""Network component for Shifter range provisioning.

This component creates the network infrastructure for a logical subnet:
- AWS Subnet (/28 for logical subnets, /24 for legacy single-subnet)
- Security Group (intra-subnet unrestricted, VPC CIDR for return traffic)
- Route Table (portal peering route, S3 endpoint association)

Inter-subnet routing:
After NetworkComponents are created, RangeStack adds explicit routes from
each subnet to connected subnet CIDRs via the NGFW data ENI. This overrides
AWS's implicit local VPC route for those specific CIDRs, forcing inter-subnet
traffic through the NGFW. Internet traffic (0.0.0.0/0) uses the NAT gateway
via AWS Network Firewall, not the NGFW.
"""

import hashlib
import ipaddress
import logging
import os

import boto3
import psycopg
import pulumi
import pulumi_aws as aws

logger = logging.getLogger(__name__)


def _get_db_connection() -> psycopg.Connection:
    """Get database connection for advisory lock.

    Supports two authentication modes:
    - If DB_PASSWORD is set: Uses standard password authentication (local dev)
    - Otherwise: Uses RDS IAM authentication (ECS/production)

    Returns:
        psycopg.Connection: Active database connection.

    Raises:
        RuntimeError: If connection fails or required env vars are missing.
    """
    db_host = os.environ.get("DB_HOST")
    db_port = int(os.environ.get("DB_PORT", 5432))
    db_user = os.environ.get("DB_USER")
    db_name = os.environ.get("DB_NAME")
    db_password = os.environ.get("DB_PASSWORD")

    if not all([db_host, db_user, db_name]):
        raise RuntimeError("Missing DB_HOST, DB_USER, or DB_NAME environment variables")

    # Local dev mode: use password auth
    if db_password:
        return psycopg.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )

    # Production mode: use RDS IAM auth
    aws_region = os.environ.get("AWS_REGION")
    if not aws_region:
        raise RuntimeError("Missing AWS_REGION environment variable for RDS IAM auth")

    client = boto3.client("rds")
    token = client.generate_db_auth_token(
        DBHostname=db_host,
        Port=db_port,
        DBUsername=db_user,
        Region=aws_region,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def _get_vpc_lock_id(vpc_id: str) -> int:
    """Generate a consistent lock ID from VPC ID for advisory lock.

    Uses MD5 hash of VPC ID to create a deterministic 32-bit integer
    that can be used with PostgreSQL advisory locks.

    Args:
        vpc_id: The VPC ID (e.g., "vpc-1234567890abcdef0").

    Returns:
        A 32-bit integer suitable for pg_advisory_lock.
    """
    # Use first 8 hex chars of MD5 hash as lock ID (32-bit integer)
    # MD5 is used here for consistent hashing, not cryptographic security
    hash_hex = hashlib.md5(vpc_id.encode(), usedforsecurity=False).hexdigest()[:8]
    return int(hash_hex, 16)


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


def allocate_subnets(vpc_id: str, cidr_prefix: str, count: int, subnet_size: int = 28) -> list[str]:
    """Allocate multiple subnets atomically with a single lock.

    This is the preferred method for allocating subnets for a range with multiple
    logical subnets. It holds the advisory lock for the entire allocation, preventing
    race conditions where multiple subnets in the same range get the same CIDR.

    Args:
        vpc_id: The VPC ID to allocate subnets in.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        count: Number of subnets to allocate.
        subnet_size: The subnet prefix length (24 or 28). Default 28.

    Returns:
        List of allocated CIDR blocks (e.g., ["10.1.2.0/28", "10.1.2.16/28"]).

    Raises:
        RuntimeError: If not enough free subnets can be found.
        ValueError: If subnet_size is not 24 or 28, or count < 1.
    """
    if subnet_size not in (24, 28):
        raise ValueError(f"subnet_size must be 24 or 28, got {subnet_size}")
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")

    logger.info(
        "Allocating %d /%d subnets in VPC %s with prefix %s",
        count,
        subnet_size,
        vpc_id,
        cidr_prefix,
    )

    # Use advisory lock to prevent concurrent subnet allocations in the same VPC
    lock_id = _get_vpc_lock_id(vpc_id)
    logger.debug("Acquiring advisory lock %d for VPC %s", lock_id, vpc_id)

    try:
        with _get_db_connection() as conn, conn.cursor() as cur:
            # Acquire advisory lock (blocks other allocations for this VPC)
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            logger.debug("Acquired advisory lock %d", lock_id)

            try:
                # Allocate all subnets with the lock held
                return _allocate_subnets_internal(vpc_id, cidr_prefix, count, subnet_size)
            finally:
                # Always release the lock
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                logger.debug("Released advisory lock %d", lock_id)
    except psycopg.Error as e:
        # If DB connection fails, fall back to unlocked allocation
        # This is riskier but AWS will reject duplicate CIDRs anyway
        logger.warning(
            "Failed to acquire advisory lock for subnet allocation (falling back to unlocked): %s",
            e,
        )
        return _allocate_subnets_internal(vpc_id, cidr_prefix, count, subnet_size)


def _allocate_subnets_internal(vpc_id: str, cidr_prefix: str, count: int, subnet_size: int) -> list[str]:
    """Internal multi-subnet allocation (called with advisory lock held).

    Args:
        vpc_id: The VPC ID to check.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        count: Number of subnets to allocate.
        subnet_size: The subnet prefix length (24 or 28).

    Returns:
        List of allocated CIDR blocks.

    Raises:
        RuntimeError: If not enough free subnets can be found.
    """
    existing_networks = _get_existing_subnets(vpc_id)
    pulumi.log.info(f"Found {len(existing_networks)} existing subnets in VPC {vpc_id}")

    # Generate candidate CIDRs based on subnet size
    if subnet_size == 24:
        candidates = _generate_slash24_candidates(cidr_prefix)
    else:
        candidates = _generate_slash28_candidates(cidr_prefix)

    allocated: list[str] = []
    allocated_networks: list[ipaddress.IPv4Network] = []

    for candidate_cidr in candidates:
        if len(allocated) >= count:
            break

        candidate_network = ipaddress.ip_network(candidate_cidr)

        # Check against existing AWS subnets
        has_aws_conflict = any(candidate_network.overlaps(existing) for existing in existing_networks)

        # Check against already-allocated subnets in this batch
        has_batch_conflict = any(candidate_network.overlaps(already) for already in allocated_networks)

        if not has_aws_conflict and not has_batch_conflict:
            logger.info("Allocated subnet: %s", candidate_cidr)
            pulumi.log.info(f"Allocated subnet: {candidate_cidr}")
            allocated.append(candidate_cidr)
            allocated_networks.append(candidate_network)

    if len(allocated) < count:
        # Not enough free subnets - critical infrastructure issue
        _publish_subnet_exhaustion_alarm(vpc_id, cidr_prefix, subnet_size)
        raise RuntimeError(
            f"Could not allocate {count} /{subnet_size} subnets in VPC {vpc_id}. "
            f"Only {len(allocated)} free subnets available in prefix {cidr_prefix}."
        )

    return allocated


def _find_free_subnet(vpc_id: str, cidr_prefix: str, subnet_size: int = 24) -> str:
    """Find a free subnet in the VPC by querying AWS.

    NOTE: For ranges with multiple subnets, use allocate_subnets() instead to
    avoid race conditions. This function is kept for backwards compatibility.

    Uses a PostgreSQL advisory lock to prevent concurrent provisions from
    allocating the same CIDR. The lock is scoped to the VPC ID, so provisions
    in different VPCs can proceed in parallel.

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
        RuntimeError: If no free subnet can be found or DB lock fails.
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

    # Use advisory lock to prevent concurrent subnet allocations in the same VPC
    lock_id = _get_vpc_lock_id(vpc_id)
    logger.debug("Acquiring advisory lock %d for VPC %s", lock_id, vpc_id)

    try:
        with _get_db_connection() as conn, conn.cursor() as cur:
            # Acquire advisory lock (blocks other allocations for this VPC)
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            logger.debug("Acquired advisory lock %d", lock_id)

            try:
                # Now safely find a free subnet with the lock held
                return _find_free_subnet_internal(vpc_id, cidr_prefix, subnet_size)
            finally:
                # Always release the lock
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                logger.debug("Released advisory lock %d", lock_id)
    except psycopg.Error as e:
        # If DB connection fails, fall back to unlocked allocation
        # AWS will reject duplicate CIDRs anyway, so this is safe
        logger.warning(
            "Failed to acquire advisory lock for subnet allocation (falling back to unlocked): %s",
            e,
        )
        return _find_free_subnet_internal(vpc_id, cidr_prefix, subnet_size)


def _find_free_subnet_internal(vpc_id: str, cidr_prefix: str, subnet_size: int) -> str:
    """Internal subnet finding logic (called with or without advisory lock).

    Args:
        vpc_id: The VPC ID to check.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        subnet_size: The subnet prefix length (24 or 28).

    Returns:
        A free CIDR block.

    Raises:
        RuntimeError: If no free subnet can be found.
    """
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
    - Security Group (intra-subnet unrestricted, VPC CIDR for return traffic)
    - Route Table (portal route, S3 endpoint association)

    Note: Inter-subnet routes via NGFW ENI are added by RangeStack, not here.

    Attributes:
        subnet: The created subnet resource.
        subnet_id: The subnet ID.
        subnet_cidr: The CIDR block of the subnet.
        security_group: The created security group.
        security_group_id: The security group ID.
        route_table: The created route table.
        route_table_id: The route table ID.
    """

    subnet: aws.ec2.Subnet
    subnet_id: pulumi.Output[str]
    subnet_cidr: pulumi.Output[str]
    security_group: aws.ec2.SecurityGroup
    security_group_id: pulumi.Output[str]
    route_table: aws.ec2.RouteTable
    route_table_id: pulumi.Output[str]

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
        s3_endpoint_id: str = "",
        firewall_endpoint_id: str = "",
        portal_vpc_cidr: str = "",
        portal_vpc_peering_id: str = "",
        allocated_cidr: str = "",
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
            s3_endpoint_id: S3 Gateway VPC Endpoint ID for agent downloads.
            firewall_endpoint_id: AWS Network Firewall endpoint ID for internet egress.
            portal_vpc_cidr: Portal VPC CIDR block for SSH access. Empty = no portal access.
            portal_vpc_peering_id: VPC peering connection ID for portal route. Empty = no route.
            allocated_cidr: Pre-allocated CIDR block. If provided, skips allocation.
                Use allocate_subnets() to get CIDRs for multi-subnet ranges.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NetworkComponent", name, None, opts)
        self._s3_endpoint_id = s3_endpoint_id
        self._firewall_endpoint_id = firewall_endpoint_id
        self._portal_vpc_cidr = portal_vpc_cidr
        self._portal_vpc_peering_id = portal_vpc_peering_id

        logger.info(
            "Creating NetworkComponent: name=%s, subnet_name=%s, size=/%d, cidr=%s",
            name,
            subnet_name,
            subnet_size,
            allocated_cidr or "auto",
        )

        # Use pre-allocated CIDR if provided, otherwise find one
        if allocated_cidr:
            logger.debug("Using pre-allocated CIDR: %s", allocated_cidr)
        else:
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
        self._create_security_group(name, vpc_id, vpc_cidr, allocated_cidr, common_tags, self._portal_vpc_cidr)

        # Create route table for this subnet
        self._create_route_table(name, vpc_id, common_tags)

        # Associate route table with S3 VPC endpoint for agent downloads
        self._associate_s3_endpoint(name)

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
        """Build common tags for all resources using shared helper.

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
        from components.tags import build_common_tags

        return build_common_tags(
            user_id=user_id,
            environment=environment,
            request_uuid=request_uuid,
            range_id=range_id,
            unit_type="subnet" if subnet_uuid else None,
            unit_uuid=subnet_uuid if subnet_uuid else None,
            unit_name=subnet_name if subnet_name else None,
        )

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
        portal_vpc_cidr: str = "",
    ) -> None:
        """Create security group for this subnet.

        Rules:
        - Inbound: Allow ALL from same subnet CIDR (intra-subnet unrestricted)
        - Inbound: Allow ALL from VPC CIDR (for NGFW return traffic)
        - Inbound: Allow SSH (port 22) from portal VPC CIDR (for terminal access)
        - Outbound: Allow ALL

        Args:
            name: Resource name prefix.
            vpc_id: VPC ID.
            vpc_cidr: VPC CIDR block for return traffic rule.
            subnet_cidr: This subnet's CIDR block.
            common_tags: Common tags dict.
            portal_vpc_cidr: Portal VPC CIDR for SSH access. Empty = no portal access.
        """
        subnet_name_tag = common_tags.get("shifter:subnet_name", "default")

        # Build ingress rules
        ingress_rules: list[aws.ec2.SecurityGroupIngressArgs] = [
            # Allow all intra-subnet traffic
            aws.ec2.SecurityGroupIngressArgs(
                protocol="-1",
                from_port=0,
                to_port=0,
                cidr_blocks=[subnet_cidr],
                description="Allow all intra-subnet traffic",
            ),
            # Allow all from VPC (NGFW return traffic for inter-subnet inspection)
            aws.ec2.SecurityGroupIngressArgs(
                protocol="-1",
                from_port=0,
                to_port=0,
                cidr_blocks=[vpc_cidr],
                description="Allow NGFW return traffic from VPC",
            ),
        ]

        # Add SSH and RDP access from portal VPC if configured
        if portal_vpc_cidr:
            logger.debug(
                "Adding SSH/RDP ingress rules from portal VPC CIDR %s for subnet %s",
                portal_vpc_cidr,
                name,
            )
            # SSH for terminal access
            ingress_rules.append(
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="tcp",
                    from_port=22,
                    to_port=22,
                    cidr_blocks=[portal_vpc_cidr],
                    description="Allow SSH from portal for terminal access",
                ),
            )
            # RDP for Guacamole access
            ingress_rules.append(
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="tcp",
                    from_port=3389,
                    to_port=3389,
                    cidr_blocks=[portal_vpc_cidr],
                    description="Allow RDP from portal for Guacamole access",
                ),
            )
        else:
            logger.warning(
                "No portal_vpc_cidr configured for subnet %s - terminal SSH/RDP access will not work",
                name,
            )

        self.security_group = aws.ec2.SecurityGroup(
            f"{name}-sg",
            vpc_id=vpc_id,
            description=f"Security group for {subnet_name_tag} subnet",
            ingress=ingress_rules,
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
        Inter-subnet routes through NGFW ENI are added separately if NGFW is enabled.
        Portal VPC route is added if portal_vpc_cidr and portal_vpc_peering_id are set.

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

        # Add route to portal VPC for SSH terminal access
        if self._portal_vpc_cidr and self._portal_vpc_peering_id:
            aws.ec2.Route(
                f"{name}-portal-route",
                route_table_id=self.route_table.id,
                destination_cidr_block=self._portal_vpc_cidr,
                vpc_peering_connection_id=self._portal_vpc_peering_id,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[self.route_table],
                ),
            )
            logger.debug("Added portal VPC route to route table for subnet %s", name)
        elif self._portal_vpc_cidr:
            logger.warning(
                "Portal VPC CIDR configured but no peering ID - terminal SSH routing will not work for subnet %s",
                name,
            )

        # Add default route to AWS Network Firewall for filtered internet egress
        # Traffic flow: Subnet -> Firewall -> NAT -> Internet
        # The firewall filters egress to only allow PANW domains
        if self._firewall_endpoint_id:
            aws.ec2.Route(
                f"{name}-firewall-route",
                route_table_id=self.route_table.id,
                destination_cidr_block="0.0.0.0/0",
                vpc_endpoint_id=self._firewall_endpoint_id,
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[self.route_table],
                ),
            )
            logger.debug("Added firewall route to route table for subnet %s", name)
        else:
            logger.warning(
                "No firewall endpoint ID configured - internet egress will not work for subnet %s",
                name,
            )

        logger.debug("Created route table for subnet %s", name)

    def _associate_s3_endpoint(self, name: str) -> None:
        """Associate route table with S3 VPC Gateway endpoint.

        This allows instances in the subnet to access S3 for agent downloads
        without requiring internet access or NAT. The S3 Gateway endpoint
        automatically adds routes for S3 prefix lists to associated route tables.

        Args:
            name: Resource name prefix for the association resource.
        """
        if not self._s3_endpoint_id:
            logger.debug("No S3 endpoint ID provided, skipping S3 endpoint association")
            return

        logger.info(
            "Associating route table with S3 endpoint %s",
            self._s3_endpoint_id,
        )

        aws.ec2.VpcEndpointRouteTableAssociation(
            f"{name}-s3-endpoint-assoc",
            vpc_endpoint_id=self._s3_endpoint_id,
            route_table_id=self.route_table.id,
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[self.route_table],
            ),
        )

        logger.debug("Associated route table with S3 endpoint for subnet %s", name)

    def add_route_to_ngfw(
        self,
        name: str,
        destination_cidr: pulumi.Output[str],
        ngfw_eni_id: str,
        opts: pulumi.ResourceOptions | None = None,
    ) -> aws.ec2.Route:
        """Add a route to another subnet's CIDR through NGFW data ENI.

        This overrides AWS's implicit local VPC route for that specific CIDR,
        forcing traffic through the NGFW for inspection instead of direct routing.

        Use this after all NetworkComponents are created to add inter-subnet
        routes that force traffic between connected subnets through the NGFW.

        Args:
            name: Unique resource name for this route.
            destination_cidr: The destination subnet's CIDR block (Pulumi Output).
            ngfw_eni_id: The NGFW data ENI ID to route traffic through.
            opts: Optional Pulumi resource options.

        Returns:
            The created Route resource.
        """
        logger.debug("Adding inter-subnet route %s via NGFW ENI %s", name, ngfw_eni_id)

        return aws.ec2.Route(
            name,
            route_table_id=self.route_table.id,
            destination_cidr_block=destination_cidr,
            network_interface_id=ngfw_eni_id,
            opts=opts or pulumi.ResourceOptions(parent=self),
        )

    def add_blackhole_route(
        self,
        name: str,
        destination_cidr: pulumi.Output[str],
        opts: pulumi.ResourceOptions | None = None,
    ) -> aws.ec2.Route:
        """Add a blackhole route to drop traffic to a destination.

        Creates a route that drops all traffic to the specified CIDR,
        preventing direct communication between non-connected subnets.

        Args:
            name: Unique resource name for this route.
            destination_cidr: The destination CIDR block to blackhole.
            opts: Optional Pulumi resource options.

        Returns:
            The created Route resource.
        """
        logger.debug("Adding blackhole route %s", name)

        return aws.ec2.Route(
            name,
            route_table_id=self.route_table.id,
            destination_cidr_block=destination_cidr,
            opts=opts or pulumi.ResourceOptions(parent=self),
            # No target = blackhole route
        )

    def _register_outputs(self) -> None:
        """Register Pulumi outputs."""
        self.register_outputs(
            {
                "subnetId": self.subnet_id,
                "subnetCidr": self.subnet_cidr,
                "securityGroupId": self.security_group_id,
                "routeTableId": self.route_table_id,
            }
        )
