"""Network utilities for subnet allocation.

Provides CIDR allocation for range subnets using PostgreSQL advisory locks
to prevent concurrent allocations of the same CIDR.
"""

import hashlib
import ipaddress
import logging
import os

import boto3
from django.db import connection

logger = logging.getLogger(__name__)


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
        with connection.cursor() as cursor:
            # Acquire advisory lock (blocks other allocations for this VPC)
            cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
            logger.debug("Acquired advisory lock %d", lock_id)

            try:
                # Allocate all subnets with the lock held
                return _allocate_subnets_internal(vpc_id, cidr_prefix, count, subnet_size)
            finally:
                # Always release the lock
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
                logger.debug("Released advisory lock %d", lock_id)
    except Exception as e:
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
    logger.info("Found %d existing subnets in VPC %s", len(existing_networks), vpc_id)

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

        candidate_network = ipaddress.IPv4Network(candidate_cidr)

        # Check against existing AWS subnets
        has_aws_conflict = any(candidate_network.overlaps(existing) for existing in existing_networks)

        # Check against already-allocated subnets in this batch
        has_batch_conflict = any(candidate_network.overlaps(already) for already in allocated_networks)

        if not has_aws_conflict and not has_batch_conflict:
            logger.info("Allocated subnet: %s", candidate_cidr)
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
        with connection.cursor() as cursor:
            # Acquire advisory lock (blocks other allocations for this VPC)
            cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
            logger.debug("Acquired advisory lock %d", lock_id)

            try:
                # Now safely find a free subnet with the lock held
                return _find_free_subnet_internal(vpc_id, cidr_prefix, subnet_size)
            finally:
                # Always release the lock
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
                logger.debug("Released advisory lock %d", lock_id)
    except Exception as e:
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
    logger.info("Found %d existing subnets in VPC %s", len(existing_networks), vpc_id)

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
        candidate_network = ipaddress.IPv4Network(candidate_cidr)

        has_conflict = any(candidate_network.overlaps(existing) for existing in existing_networks)

        if not has_conflict:
            logger.info("Found free subnet: %s", candidate_cidr)
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
