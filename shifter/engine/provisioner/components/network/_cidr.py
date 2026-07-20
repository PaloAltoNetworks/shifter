"""CIDR candidate generation and single-subnet lookup.

Deterministic /24 and /28 candidate generation, plus the legacy
single-subnet finder (``_find_free_subnet``) used by callers that haven't
migrated to ``allocate_subnets()``.
"""

import ipaddress
import logging

from ._db import _get_existing_subnets, _publish_subnet_exhaustion_alarm

logger = logging.getLogger(__name__)


def _find_free_subnet(vpc_id: str, cidr_prefix: str, subnet_size: int = 24) -> str:
    """Find a free subnet in the VPC by querying AWS.

    NOTE: For ranges with multiple subnets, use allocate_subnets() instead.

    Uses a PostgreSQL table-level EXCLUSIVE lock on engine_subnetallocation
    to serialize all concurrent allocations.

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

    # Late-bound call to ``components.network._get_db_connection`` so test
    # patches applied at the package level still apply here.
    from components import network as _net

    # Table-level lock serializes ALL concurrent allocations.
    # No silent fallback — if the lock fails, provisioning fails.
    with _net._get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("LOCK TABLE engine_subnetallocation IN EXCLUSIVE MODE")
        logger.info("Acquired table lock on engine_subnetallocation for VPC %s", vpc_id)

        return _find_free_subnet_internal(vpc_id, cidr_prefix, subnet_size)


def _find_free_subnet_internal(vpc_id: str, cidr_prefix: str, subnet_size: int) -> str:
    """Internal subnet finding logic (called with table lock held).

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
