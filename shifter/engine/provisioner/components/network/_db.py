"""Provider network observation and the connection used to reach coordination.

What used to live here -- the allocation-table reads and writes, and a second
database connection factory -- is gone. Reservation state belongs to the Engine
(ADR-043-R6), and after #1838 this process has no privilege to touch that table;
the only thing it still contributes is what the Engine cannot see for itself, the
provider's current view of the network.
"""

import ipaddress
import logging
from typing import TYPE_CHECKING

from cloud.exceptions import CloudNetworkInventoryError

if TYPE_CHECKING:
    import psycopg

    from cloud.types import NetworkInventory

logger = logging.getLogger(__name__)


def _get_db_connection() -> "psycopg.Connection":
    """Return a database connection from the canonical provisioner factory.

    Delegates rather than re-implementing the TLS/IAM-token handshake: this module
    used to carry a second copy of it, which meant two places to keep the deployed
    authentication posture correct.
    """
    from provisioner_db import get_db_connection

    return get_db_connection()


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

    Fails closed on an entry that cannot be parsed. This observation becomes the
    occupied set the coordination routine reconciles drift against, and a silently
    dropped entry is indistinguishable from "that subnet does not exist" -- which
    is exactly how the allocator would come to hand out a CIDR the provider is
    already using. An incomplete observation must therefore stop the reservation,
    not quietly narrow it.

    Valid IPv6 networks are the one exception, and they are skipped rather than
    dropped blindly: allocation carves IPv4 subnets only, and an IPv6 network
    cannot overlap an IPv4 candidate, so omitting it cannot mask a conflict.

    Args:
        vpc_id: Provider network identifier to check.

    Returns:
        List of existing IPv4 subnet networks.

    Raises:
        CloudNetworkInventoryError: The provider returned an entry that is not a
            parseable network.
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
        except ValueError as exc:
            # The value itself is deliberately not logged or surfaced: it is
            # provider output, and the caller only needs to know the observation
            # is unusable.
            raise CloudNetworkInventoryError(
                f"Cloud network inventory returned an unparseable subnet for network {vpc_id}"
            ) from exc
        if isinstance(network, ipaddress.IPv4Network):
            existing_networks.append(network)

    logger.debug("Found %d existing subnets in network %s", len(existing_networks), vpc_id)
    return existing_networks
