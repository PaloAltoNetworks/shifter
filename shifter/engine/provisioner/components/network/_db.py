"""Database-backed subnet inventory helpers.

DB connection (advisory-lock aware), cloud network inventory adapter access,
exhaustion alerting, and the engine_subnetallocation table read/write
helpers used by subnet allocation and lookup.
"""

import ipaddress
import logging
import os
from typing import TYPE_CHECKING

import psycopg

from cloud.exceptions import CloudNetworkInventoryError

if TYPE_CHECKING:
    from cloud.types import NetworkInventory

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

    # validated above
    assert db_host is not None
    # validated above
    assert db_user is not None
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


def _get_network_inventory() -> "NetworkInventory":
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
        # Late-bound call to ``components.network._get_network_inventory`` so
        # test patches applied at the package level still apply here.
        from components import network as _net

        inventory = _net._get_network_inventory()
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
    # Late-bound call to ``components.network._get_network_inventory`` so test
    # patches applied at the package level still apply here.
    from components import network as _net

    inventory = _net._get_network_inventory()
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
