"""Network utilities for Shifter range provisioning.

Subnet allocation and deallocation functions for range infrastructure.
Uses PostgreSQL advisory locks to serialize concurrent allocations and
prevent CIDR conflicts.

The implementation is split across private submodules (``_db``, ``_allocate``,
``_cidr``) and re-exported here so callers continue to use
``from components.network import X``.

``psycopg`` is re-exported too: tests patch ``components.network.psycopg.connect``
directly, which requires ``psycopg`` to be resolvable as a package-level
attribute (patch resolves the dotted path one attribute at a time). Since
``psycopg`` is a single cached module object, mutating its ``connect``
attribute here is visible to every submodule that also does ``import psycopg``.
"""

import psycopg

from ._allocate import (
    _allocate_subnets_internal,
    allocate_subnets,
    get_allocated_cidrs,
    release_subnet_allocations,
)
from ._cidr import (
    _find_free_subnet,
    _find_free_subnet_internal,
    _generate_slash24_candidates,
    _generate_slash28_candidates,
)
from ._db import (
    _get_db_connection,
    _get_existing_subnets,
    _get_network_inventory,
    _get_tracked_subnets,
    _publish_subnet_exhaustion_alarm,
    _record_allocation,
    _record_allocations,
)

__all__ = [
    "_allocate_subnets_internal",
    "_find_free_subnet",
    "_find_free_subnet_internal",
    "_generate_slash24_candidates",
    "_generate_slash28_candidates",
    "_get_db_connection",
    "_get_existing_subnets",
    "_get_network_inventory",
    "_get_tracked_subnets",
    "_publish_subnet_exhaustion_alarm",
    "_record_allocation",
    "_record_allocations",
    "allocate_subnets",
    "get_allocated_cidrs",
    "psycopg",
    "release_subnet_allocations",
]
