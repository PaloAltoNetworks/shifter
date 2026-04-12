"""Network utilities for Shifter range provisioning.

Subnet allocation and deallocation functions for range infrastructure.
Uses PostgreSQL advisory locks to serialize concurrent allocations and
prevent CIDR conflicts.
"""

import ipaddress
import logging
import os

import psycopg

from cloud.exceptions import CloudNetworkInventoryError

logger = logging.getLogger(__name__)


def _get_db_connection() -> psycopg.Connection:
    """Get database connection for advisory lock.

    Supports two authentication modes:
    - If DB_PASSWORD is set: Uses standard password authentication (local dev)
    - Otherwise: Uses the active cloud DB auth adapter (IAM-based in deployed environments)

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

    assert db_host is not None  # validated above
    assert db_user is not None  # validated above
    from cloud import get_db_auth

    auth = get_db_auth()
    token = auth.generate_auth_token(
        hostname=db_host,
        port=db_port,
        username=db_user,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def _get_network_inventory():
    """Resolve the active provider's network inventory adapter lazily."""
    from cloud import get_network_inventory

    return get_network_inventory()


def _publish_subnet_exhaustion_alarm(vpc_id: str, cidr_prefix: str, subnet_size: int) -> None:
    """Publish a provider-aware exhaustion alarm and log for subnet exhaustion.

    This is a critical infrastructure alert - if we run out of subnets,
    users cannot launch ranges.

    Args:
        vpc_id: The provider network that has no free subnets.
        cidr_prefix: The CIDR prefix that was searched.
        subnet_size: The subnet size that was requested (e.g., 24 or 28).
    """
    try:
        inventory = _get_network_inventory()
        inventory.publish_subnet_exhaustion_alarm(vpc_id, cidr_prefix, subnet_size)
    except CloudNetworkInventoryError as e:
        logger.warning(
            "Failed to publish subnet exhaustion alarm for network %s: %s",
            vpc_id,
            e,
        )


def _get_existing_subnets(vpc_id: str) -> list[ipaddress.IPv4Network]:
    """Query the active cloud provider for all existing subnets in a network.

    Args:
        vpc_id: Provider network identifier to check.

    Returns:
        List of existing subnet networks.
    """
    inventory = _get_network_inventory()
    existing_cidrs = inventory.list_subnet_cidrs(vpc_id)
    existing_networks: list[ipaddress.IPv4Network] = []
    for cidr in existing_cidrs:
        try:
            network = ipaddress.ip_network(cidr)
            if isinstance(network, ipaddress.IPv4Network):
                existing_networks.append(network)
        except ValueError:
            logger.warning("Invalid CIDR in cloud network inventory response: %s", cidr)
            continue

    logger.debug("Found %d existing subnets in network %s", len(existing_networks), vpc_id)
    return existing_networks


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

    # Table-level lock serializes ALL concurrent allocations.
    # No silent fallback — if the lock fails, provisioning fails.
    with _get_db_connection() as conn, conn.cursor() as cur:
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


def _get_tracked_subnets(
    vpc_id: str,
    conn: psycopg.Connection,
) -> list[ipaddress.IPv4Network]:
    """Query allocation table for all tracked subnets in a VPC.

    Row exists = occupied. No status column, no stale logic.

    Args:
        vpc_id: The VPC ID to check.
        conn: DB connection (must be provided).

    Returns:
        List of tracked networks.
    """
    networks: list[ipaddress.IPv4Network] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cidr FROM engine_subnetallocation WHERE vpc_id = %s",
            (vpc_id,),
        )
        for (cidr,) in cur.fetchall():
            try:
                networks.append(ipaddress.IPv4Network(cidr))
            except ValueError:
                logger.warning("Invalid CIDR in allocation table: %s", cidr)

    return networks


def _record_allocation(
    conn: psycopg.Connection,
    vpc_id: str,
    cidr: str,
    subnet_size: int,
    range_id: int,
    request_id: str,
) -> None:
    """Insert a single allocation row. Idempotent via ON CONFLICT.

    Args:
        conn: Active DB connection holding the table lock.
        vpc_id: The VPC ID.
        cidr: CIDR string to record.
        subnet_size: Subnet prefix length (24 or 28).
        range_id: Range database ID (0 for drift-discovered subnets).
        request_id: Request UUID for correlation (empty for drift-discovered).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO engine_subnetallocation
                (vpc_id, cidr, subnet_size, range_id, request_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (vpc_id, cidr) DO NOTHING
            """,
            (vpc_id, cidr, subnet_size, range_id, request_id),
        )


def _record_allocations(
    conn: psycopg.Connection,
    vpc_id: str,
    cidrs: list[str],
    subnet_size: int,
    range_id: int,
    request_id: str,
) -> None:
    """Insert allocation rows for allocated CIDRs.

    Called inside the table lock. Failures are fatal.

    Args:
        conn: Active DB connection holding the table lock.
        vpc_id: The VPC ID.
        cidrs: List of CIDR strings to record.
        subnet_size: Subnet prefix length (24 or 28).
        range_id: Range database ID.
        request_id: Request UUID for correlation.
    """
    for cidr in cidrs:
        _record_allocation(conn, vpc_id, cidr, subnet_size, range_id, request_id)
    logger.info(
        "Recorded %d subnet allocations for request %s",
        len(cidrs),
        request_id,
    )


def release_subnet_allocations(request_id: str) -> None:
    """Delete allocation rows when a range is destroyed or failed.

    Args:
        request_id: Request UUID whose allocations to remove.
    """
    with _get_db_connection() as conn, conn.cursor() as cur:
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
    with _get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cidr FROM engine_subnetallocation WHERE range_id = %s ORDER BY created_at",
            (range_id,),
        )
        cidrs = [row[0] for row in cur.fetchall()]
    logger.info("Retrieved %d allocated CIDRs for range %d", len(cidrs), range_id)
    return cidrs


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

    # Table-level lock serializes ALL concurrent allocations.
    # No silent fallback — if the lock fails, provisioning fails.
    with _get_db_connection() as conn, conn.cursor() as cur:
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
