"""Per-range subnet CIDR reservation, lookup, and post-destroy cleanup.

Owns the range's subnet CIDR lifecycle against the Engine coordination surface:
reservation before a provision, lookup for destroy, and the best-effort release
paths used by destroy and provision compensation.

The realized CIDRs are an *operation-local realization value*, not a change to the
range's authored spec. Before #1838 reservation wrote them back into
``mission_control_range.range_config`` and later repaired that column from the
allocation table -- which made authored intent double as runtime scratch state and
required a column write grant to sustain. ADR-043-R6 separates the two: authored
intent stays untouched, realized CIDRs live in allocation state, and each
operation composes what it needs from both.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from config import load_range_network_config
from provisioner_db import mark_range_instances_destroyed
from provisioner_db_appends import OperationRef

logger = logging.getLogger(__name__)

# Used only when the network config carries no explicit network_cidr; matches the
# dev environment's default range VPC. Production callers always populate
# range_network.network_cidr from environment terraform.
_DEFAULT_RANGE_VPC_CIDR = "10.1.0.0/16"  # NOSONAR(S1313)

# The prefix length Cyberscript ranges have always requested. The coordination
# contract keeps it a parameter so the existing /24 policy can reuse the boundary.
_RANGE_SUBNET_PREFIX_LENGTH = 28


def _authored_subnet_identities(range_spec: dict[str, Any]) -> tuple[str, ...]:
    """Return the authored subnets' stable identities, in authored order.

    These are part of the reservation's retry shape: a retry that reorders or
    re-labels the authored subnets would realize a different range, so the
    coordination routine must be able to tell it apart from a genuine repeat.

    Prefers the DSL ``uuid`` and falls back to ``name`` -- both are stable within
    a compiled spec, and position disambiguates the rest.
    """
    identities: list[str] = []
    for position, subnet in enumerate(range_spec.get("subnets", [])):
        identity = str(subnet.get("uuid") or subnet.get("name") or "")
        # Position keeps the identity unique and order-sensitive even when a spec
        # authored two subnets with the same name and no uuid.
        identities.append(f"{position}:{identity}")
    return tuple(identities)


def _realize_range_spec(range_spec: dict[str, Any], cidrs: tuple[str, ...]) -> dict[str, Any]:
    """Return a copy of ``range_spec`` whose subnets carry the reserved CIDRs.

    A copy, not an in-place edit: the authored spec is the persisted contract this
    operation was launched with, and mutating it makes "what was authored" and
    "what this attempt realized" the same object -- the confusion ADR-043-R6 exists
    to remove.

    Pairing is positional because the reservation is returned in authored subnet
    order, which the coordination contract guarantees by ordinal.
    """
    realized = copy.deepcopy(range_spec)
    subnets = realized.get("subnets", [])
    for subnet, cidr in zip(subnets, cidrs, strict=False):
        subnet["cidr"] = cidr
    return realized


def _reserve_range_subnet_cidrs(
    request_id: str,
    range_spec: dict[str, Any],
    *,
    operation_id: str | None,
) -> dict[str, Any]:
    """Reserve this range's subnet CIDRs and return the realized range spec.

    Args:
        request_id: The request this range was launched for.
        range_spec: The authored range spec; left unmodified.
        operation_id: The ADR-043 canonical operation generation. Required; the
            coordination routine fences the reservation on it.

    Returns:
        A realized copy of ``range_spec``. A spec with no subnets is returned
        unchanged -- there is nothing to reserve.
    """
    if not range_spec.get("subnets"):
        return range_spec

    from components.network import reserve_range_subnets

    range_network = load_range_network_config()
    reserved = reserve_range_subnets(
        operation_id=operation_id,
        request_id=request_id,
        network_id=range_network.network_id,
        network_cidr=range_network.network_cidr or _DEFAULT_RANGE_VPC_CIDR,
        subnets=_authored_subnet_identities(range_spec),
        prefix_length=_RANGE_SUBNET_PREFIX_LENGTH,
    )
    return _realize_range_spec(range_spec, reserved)


def _realized_range_spec_for_destroy(
    request_id: str,
    range_spec: dict[str, Any],
    *,
    operation_id: str | None,
) -> dict[str, Any]:
    """Return the range spec with the CIDRs this range actually holds.

    Destroy has to tear down what was built, so the CIDRs come from the owned
    reservation rather than from authored intent, which never carried them.
    """
    if not range_spec.get("subnets"):
        return range_spec

    from components.network import read_range_subnets

    reserved = read_range_subnets(operation_id=operation_id, request_id=request_id)
    if not reserved:
        logger.warning("No subnet reservation found for request %s; destroying from authored spec", request_id)
        return range_spec
    return _realize_range_spec(range_spec, reserved)


def _release_subnet_allocations_best_effort(request_id: str, *, operation_id: str | None) -> None:
    """Release subnet reservations on provision failure; never raise.

    Best effort, but never silent: a reservation that survives a failed provision
    is capacity nobody can allocate and nobody is using, so it needs an operator
    signal rather than a swallowed exception.
    """
    # The failure class is captured and logged outside the handler on purpose:
    # ``logger.exception`` would attach a full stack trace, and raw exception
    # bodies must not cross this boundary (ADR-043-R5). The type name alone is
    # enough for an operator to act on a leaked reservation.
    failure: str | None = None
    try:
        from components.network import release_range_subnets

        release_range_subnets(operation_id=operation_id, request_id=request_id)
    except Exception as e:
        failure = type(e).__name__
    if failure is not None:
        logger.error(
            "Failed to release subnet reservations for request %s; capacity may be leaked: %s",
            request_id,
            failure,
        )


def _post_destroy_cleanup(request_id: str, range_id: int, *, operation_id: str | None = None) -> None:
    """Mark range destroyed, release subnet reservations. Best-effort.

    ``operation_id`` is the ADR-043 canonical operation generation (#1834);
    threaded through to the shadow operation-result append inside
    ``mark_range_instances_destroyed`` and to the reservation release.
    """
    try:
        mark_range_instances_destroyed(
            range_id, operation=OperationRef(request_id=request_id, operation_id=operation_id)
        )
    except Exception:
        logger.exception("Failed to mark range %d as destroyed", range_id)

    _release_subnet_allocations_best_effort(request_id, operation_id=operation_id)
