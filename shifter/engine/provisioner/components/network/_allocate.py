"""Multi-subnet allocation, table-lock orchestration, release, and lookup.

Public entry points for allocating and releasing subnet CIDRs against the
engine_subnetallocation table, guarded by a PostgreSQL table-level lock.
"""

import ipaddress
import logging

import psycopg

from ._cidr import _generate_slash24_candidates, _generate_slash28_candidates
from ._db import (
    _get_existing_subnets,
    _get_tracked_subnets,
    _publish_subnet_exhaustion_alarm,
    _record_allocation,
    _record_allocations,
)

logger = logging.getLogger(__name__)


def allocate_subnets(
    vpc_id: str,
    cidr_prefix: str,
    count: int,
    subnet_size: int = 28,
    range_id: int = 0,
    request_id: str = "",
) -> list[str]:
    """Allocate multiple subnets atomically with a table-level lock.

    Uses LOCK TABLE engine_subnetallocation IN EXCLUSIVE MODE to serialize
    all concurrent subnet allocations. This prevents race conditions even
    when the table is empty.

    CIDRs are reserved in the engine_subnetallocation table inside the lock to
    prevent TOCTOU races: subsequent allocators see reservations even before
    Terraform creates the actual AWS subnets (~30-90s later).

    Args:
        vpc_id: The VPC ID to allocate subnets in.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        count: Number of subnets to allocate.
        subnet_size: The subnet prefix length (24 or 28). Default 28.
        range_id: Range DB ID for the reservation record.
        request_id: Request UUID for the reservation record.

    Returns:
        List of allocated CIDR blocks (e.g., ["10.1.2.0/28", "10.1.2.16/28"]).

    Raises:
        RuntimeError: If not enough free subnets can be found or DB lock fails.
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

    # Late-bound call to ``components.network._get_db_connection`` so test
    # patches applied at the package level still apply here.
    from components import network as _net

    # Table-level lock serializes ALL concurrent allocations.
    # No silent fallback — if the lock fails, provisioning fails.
    with _net._get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("LOCK TABLE engine_subnetallocation IN EXCLUSIVE MODE")
        logger.info("Acquired table lock on engine_subnetallocation for VPC %s", vpc_id)

        # Allocate all subnets with the lock held
        allocated = _allocate_subnets_internal(
            vpc_id,
            cidr_prefix,
            count,
            subnet_size,
            conn=conn,
        )

        # Record allocations so next allocator sees them.
        # This MUST succeed — no silent fallback.
        if range_id and request_id:
            _record_allocations(
                conn,
                vpc_id,
                allocated,
                subnet_size,
                range_id,
                request_id,
            )

        conn.commit()
        logger.info(
            "Committed %d subnet allocations for VPC %s",
            len(allocated),
            vpc_id,
        )

        return allocated


def _allocate_subnets_internal(
    vpc_id: str,
    cidr_prefix: str,
    count: int,
    subnet_size: int,
    conn: psycopg.Connection,
) -> list[str]:
    """Internal multi-subnet allocation (called with table lock held).

    Reconciles AWS state with the allocation table before picking subnets:
    - AWS subnets not in the table are inserted (drift repair)
    - Table entries are trusted even if not yet in AWS (in-flight Terraform)

    Args:
        vpc_id: The VPC ID to check.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.Y/size).
        count: Number of subnets to allocate.
        subnet_size: The subnet prefix length (24 or 28).
        conn: DB connection holding the table lock.

    Returns:
        List of allocated CIDR blocks.

    Raises:
        RuntimeError: If not enough free subnets can be found.
    """
    # 1. Get AWS reality
    aws_networks = _get_existing_subnets(vpc_id)
    logger.info("Found %d existing subnets in VPC %s", len(aws_networks), vpc_id)

    # 2. Get allocation table state
    tracked_cidrs = _get_tracked_subnets(vpc_id, conn)
    logger.info("Found %d tracked CIDRs in allocation table for VPC %s", len(tracked_cidrs), vpc_id)

    # 3. Reconcile: AWS subnets not in table → insert them
    tracked_cidr_strs = {str(n) for n in tracked_cidrs}
    drift_count = 0
    for aws_net in aws_networks:
        if str(aws_net) not in tracked_cidr_strs:
            _record_allocation(conn, vpc_id, str(aws_net), aws_net.prefixlen, 0, "")
            drift_count += 1
    if drift_count:
        logger.warning(
            "Reconciled %d AWS subnets not tracked in allocation table for VPC %s",
            drift_count,
            vpc_id,
        )

    # 4. Build merged occupied set (table + AWS + batch)
    occupied = {str(n) for n in aws_networks} | tracked_cidr_strs

    # 5. Generate candidates and find free ones
    if subnet_size == 24:
        candidates = _generate_slash24_candidates(cidr_prefix)
    else:
        candidates = _generate_slash28_candidates(cidr_prefix)

    allocated: list[str] = []

    for candidate_cidr in candidates:
        if len(allocated) >= count:
            break

        candidate_network = ipaddress.IPv4Network(candidate_cidr)

        # Check against all occupied subnets (table + AWS + this batch)
        has_conflict = any(candidate_network.overlaps(ipaddress.IPv4Network(o)) for o in occupied)

        if not has_conflict:
            logger.info("Allocated subnet: %s", candidate_cidr)
            allocated.append(candidate_cidr)
            occupied.add(candidate_cidr)

    if len(allocated) < count:
        _publish_subnet_exhaustion_alarm(vpc_id, cidr_prefix, subnet_size)
        raise RuntimeError(
            f"Could not allocate {count} /{subnet_size} subnets in VPC {vpc_id}. "
            f"Only {len(allocated)} free subnets available in prefix {cidr_prefix}."
        )

    return allocated


def release_subnet_allocations(request_id: str) -> None:
    """Delete allocation rows when a range is destroyed or failed.

    Args:
        request_id: Request UUID whose allocations to remove.
    """
    # Late-bound call to ``components.network._get_db_connection`` so test
    # patches applied at the package level still apply here.
    from components import network as _net

    with _net._get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM engine_subnetallocation WHERE request_id = %s",
            (request_id,),
        )
        conn.commit()
        logger.info("Released subnet allocations for request %s", request_id)


def get_allocated_cidrs(range_id: int) -> list[str]:
    """Look up allocated CIDRs for a range from the subnet allocation table.

    Used as a fallback when range_config doesn't have CIDRs persisted
    (e.g., ranges provisioned before the persist-on-allocate fix).

    Args:
        range_id: The range database ID.

    Returns:
        List of CIDR strings allocated to this range, ordered by creation time.
    """
    # Late-bound call to ``components.network._get_db_connection`` so test
    # patches applied at the package level still apply here.
    from components import network as _net

    with _net._get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cidr FROM engine_subnetallocation WHERE range_id = %s ORDER BY id",
            (range_id,),
        )
        cidrs = [row[0] for row in cur.fetchall()]
    logger.info("Retrieved %d allocated CIDRs for range %d", len(cidrs), range_id)
    return cidrs
