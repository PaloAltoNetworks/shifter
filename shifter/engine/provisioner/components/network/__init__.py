"""Subnet reservation for Shifter range provisioning.

Reservation is coordinated by the Engine (ADR-043-R6): this package observes the
provider network and calls the Engine-owned coordination routines, which hold the
PostgreSQL EXCLUSIVE table lock across drift reconciliation, candidate selection,
and insertion. The provisioner has no direct privilege on the allocation table.

The implementation is split across private submodules (``_db``, ``_allocate``) and
re-exported here so callers continue to use ``from components.network import X``.
"""

from ._allocate import (
    read_range_subnets,
    release_range_subnets,
    reserve_range_subnets,
)
from ._db import (
    _get_db_connection,
    _get_existing_subnets,
    _get_network_inventory,
    _publish_subnet_exhaustion_alarm,
)

__all__ = [
    "_get_db_connection",
    "_get_existing_subnets",
    "_get_network_inventory",
    "_publish_subnet_exhaustion_alarm",
    "read_range_subnets",
    "release_range_subnets",
    "reserve_range_subnets",
]
