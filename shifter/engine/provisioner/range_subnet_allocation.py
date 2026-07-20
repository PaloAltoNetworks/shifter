"""Per-range subnet CIDR allocation, recovery, and post-destroy cleanup.

Split out of ``terraform_ops`` (Sonar S104). Owns the range-spec subnet CIDR
lifecycle around the allocation table: allocation before a provision, recovery
of CIDRs lost from ``range_config``, and the best-effort release paths used by
destroy and provision compensation.
"""

from __future__ import annotations

import logging
from typing import Any

from config import load_range_network_config
from provisioner_db import _update_range_config, mark_range_instances_destroyed

logger = logging.getLogger(__name__)


def _allocate_range_subnet_cidrs(
    request_id: str,
    range_id: int,
    range_spec: dict[str, Any],
    *,
    persist_to_scenario: bool = True,
) -> list[dict[str, Any]]:
    """Allocate subnet CIDRs, optionally retaining legacy scenario persistence."""
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return spec_subnets

    from components.network import allocate_subnets

    # Fallback CIDR used only when the network config has no explicit network_cidr;
    # matches the dev environment's default range VPC. Production callers always
    # populate range_network.network_cidr from environment terraform.
    # Documented fallback CIDR; production always overrides via terraform.
    _DEFAULT_RANGE_VPC_CIDR = "10.1.0.0/16"  # NOSONAR(S1313)
    range_network = load_range_network_config()
    vpc_id = range_network.network_id
    vpc_cidr = range_network.network_cidr or _DEFAULT_RANGE_VPC_CIDR
    cidr_prefix = ".".join(vpc_cidr.split("/")[0].split(".")[:2])
    subnet_count = len(spec_subnets)
    logger.info("Allocating %d subnet CIDRs in VPC %s", subnet_count, vpc_id)
    allocated_cidrs = allocate_subnets(
        vpc_id,
        cidr_prefix,
        subnet_count,
        subnet_size=28,
        range_id=range_id,
        request_id=request_id,
    )
    logger.info("Allocated CIDRs: %s", allocated_cidrs)
    for i, subnet in enumerate(spec_subnets):
        subnet["cidr"] = allocated_cidrs[i]
    if persist_to_scenario:
        _update_range_config(range_id, range_spec)
    return spec_subnets


def _recover_missing_subnet_cidrs(range_id: int, range_spec: dict[str, Any]) -> None:
    """If range_spec lost its subnet CIDRs, repopulate from the allocation table."""
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets or spec_subnets[0].get("cidr"):
        return
    logger.warning("range_config missing CIDRs for range %d, recovering from allocation table", range_id)
    from components.network import get_allocated_cidrs

    allocated = get_allocated_cidrs(range_id)
    for i, subnet in enumerate(spec_subnets):
        if i < len(allocated):
            subnet["cidr"] = allocated[i]


def _release_subnet_allocations_best_effort(request_id: str) -> None:
    """Release subnet allocations on provision failure; never raise."""
    try:
        from components.network import release_subnet_allocations

        release_subnet_allocations(request_id)
    except Exception as e:
        logger.warning("Failed to release subnet allocations: %s", e)


def _post_destroy_cleanup(request_id: str, range_id: int) -> None:
    """Mark range destroyed, release subnet allocations. Best-effort."""
    try:
        mark_range_instances_destroyed(range_id)
    except Exception:
        logger.exception("Failed to mark range %d as destroyed", range_id)

    try:
        from components.network import release_subnet_allocations

        release_subnet_allocations(request_id)
    except Exception as e:
        logger.warning("Failed to release subnet allocations: %s", e)
