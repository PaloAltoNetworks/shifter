"""Subnet reservation, lookup, and release through the Engine coordination surface.

Before #1838 this module held the reservation policy itself: it took the table
lock, reconciled provider drift, generated candidates, and inserted rows. All of
that now lives in the Engine-owned coordination routines (engine migration 0046),
which is the only place it can live once this process loses its grants on
``engine_subnetallocation`` -- and the only way Engine callers and the provisioner
can share one policy rather than two implementations that agree by accident.

What remains here is the part the Engine genuinely cannot do: observe the cloud
provider's current subnets. That observation is handed to the routine, which
merges it as drift evidence while holding the same EXCLUSIVE table lock that has
always serialized allocation.
"""

from __future__ import annotations

import logging

from shared.subnet_coordination import (
    COORDINATION_CONTRACT_VERSION,
    READ_SQL,
    REASON_EXHAUSTED,
    RELEASE_SQL,
    RESERVE_SQL,
    SubnetCoordinationError,
    build_reservation_request,
    observations_as_pg_array,
    parse_reservation_result,
    reason_for_sqlstate,
)

logger = logging.getLogger(__name__)


def _require_generation(operation_id: str | None) -> str:
    """Return the operation generation, or fail closed when it is absent.

    ``build_reservation_request`` performs this check for the reserve path; the
    read and release paths send the id straight to the routine, so they need the
    same refusal rather than passing ``None`` down to a cast error.
    """
    if not operation_id:
        raise SubnetCoordinationError("an operation generation is required to reach subnet coordination")
    return str(operation_id)


def _reason_for(exc: BaseException) -> str | None:
    """Return the fixed reason code for a coordination failure, if recognized."""
    return reason_for_sqlstate(getattr(exc, "sqlstate", None))


def reserve_range_subnets(
    *,
    operation_id: str | None,
    request_id: str,
    network_id: str,
    network_cidr: str,
    subnets: tuple[str, ...],
    prefix_length: int = 28,
) -> tuple[str, ...]:
    """Reserve one CIDR per authored subnet and return them in that order.

    The returned order is the authored subnet order: the caller pairs element *i*
    with its *i*-th authored subnet.

    Args:
        operation_id: The ADR-043 canonical operation generation. Typed optional
            because callers hold it optionally, but it is required in fact: the
            routine fences the reservation on it, so ``None`` fails closed at the
            contract rather than reserving untracked capacity.
        request_id: The request this range was launched for.
        network_id: Provider network identifier (AWS vpc-id, GDC network name, or
            GCE network self-link).
        network_cidr: The network the subnets are carved from.
        subnets: The authored subnet identities, in authored order. Their order
            and identity are part of the reservation's retry shape, so a retry
            that reorders or re-labels them is a conflict rather than a second
            batch.
        prefix_length: Subnet prefix length (24 or 28).

    Returns:
        The reserved CIDRs, in authored subnet order.

    Raises:
        SubnetCoordinationError: The request was outside the contract, or the
            routine refused it (conflicting retry, exhausted network, stale
            generation, unknown request).
    """
    # Late-bound so package-level test patches still apply.
    from components import network as _net

    observed = _net._get_existing_subnets(network_id)
    request = build_reservation_request(
        operation_id=operation_id,
        request_id=request_id,
        network_id=network_id,
        network_cidr=network_cidr,
        prefix_length=prefix_length,
        subnets=subnets,
        observed_cidrs=[str(network) for network in observed],
    )

    logger.info(
        "Reserving %d /%d subnets in network %s (observed %d provider subnets)",
        request.subnet_count,
        request.prefix_length,
        request.network_id,
        len(request.observed_cidrs),
    )

    try:
        with _net._get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                RESERVE_SQL,
                (
                    request.contract_version,
                    request.operation_id,
                    request.request_id,
                    request.network_id,
                    request.network_cidr,
                    request.prefix_length,
                    request.subnet_count,
                    observations_as_pg_array(request.observed_cidrs),
                    request.shape_fingerprint,
                ),
            )
            rows = cur.fetchall()
            # The routine holds the EXCLUSIVE lock until this commit, so the
            # reservation is not durable -- and the lock not released -- until here.
            conn.commit()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        if reason == REASON_EXHAUSTED:
            # Nobody can launch a range without free subnets, so this is an
            # infrastructure alert and not merely a failed provision.
            _net._publish_subnet_exhaustion_alarm(network_id, network_cidr, prefix_length)
        raise SubnetCoordinationError(f"subnet reservation failed: {reason}") from None

    reserved = parse_reservation_result(rows, expected_count=request.subnet_count)
    logger.info("Reserved %d subnets for request %s", len(reserved), request_id)
    return reserved


def read_range_subnets(*, operation_id: str | None, request_id: str) -> tuple[str, ...]:
    """Return the CIDRs already reserved for this request, in authored order.

    Used by destroy and by a provision retry. An empty result is legitimate: it
    means the range never reached reservation. A missing ``operation_id`` fails
    closed for the same reason reservation does.
    """
    _require_generation(operation_id)
    from components import network as _net

    try:
        with _net._get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(READ_SQL, (COORDINATION_CONTRACT_VERSION, str(operation_id), str(request_id)))
            rows = cur.fetchall()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        raise SubnetCoordinationError(f"subnet reservation read failed: {reason}") from None

    reserved = parse_reservation_result(rows, expected_count=len(rows))
    logger.info("Read %d reserved subnets for request %s", len(reserved), request_id)
    return reserved


def release_range_subnets(*, operation_id: str | None, request_id: str) -> int:
    """Release this request's reservations and return how many rows went.

    Idempotent. Drift-observed occupancy is never released by this call -- it is
    evidence about the provider, not something this range reserved. A missing
    ``operation_id`` fails closed.
    """
    _require_generation(operation_id)
    from components import network as _net

    try:
        with _net._get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(RELEASE_SQL, (COORDINATION_CONTRACT_VERSION, str(operation_id), str(request_id)))
            row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        raise SubnetCoordinationError(f"subnet reservation release failed: {reason}") from None

    released = int(row[0]) if row and row[0] is not None else 0
    logger.info("Released %d subnet reservations for request %s", released, request_id)
    return released
