"""Engine-side facade over the subnet-coordination routines (ADR-043-R6, #1838).

Engine callers and the separately deployed provisioner reach the *same* database
routines, so there is one reservation policy and one persistence path. This module
adds no selection logic of its own -- doing so would recreate the split brain the
phase exists to remove.

Its only real job beyond calling the routine is collapsing driver failures into the
fixed reason codes in ``shared.subnet_coordination``: SQL text, routine and table
names, and raw driver exceptions stop here and never reach range error text,
events, audit context, or an API envelope.
"""

from __future__ import annotations

from django.db import connection

from shared.subnet_coordination import (
    COORDINATION_CONTRACT_VERSION,
    READ_SQL,
    RELEASE_SQL,
    RESERVE_SQL,
    SubnetCoordinationError,
    SubnetReservationRequest,
    observations_as_pg_array,
    parse_reservation_result,
    reason_for_sqlstate,
)

__all__ = [
    "read_subnet_reservation",
    "release_subnet_reservation",
    "reserve_subnet_cidrs",
]


def _reason_for(exc: BaseException) -> str | None:
    """Return the fixed reason code for a coordination failure, if recognized.

    Django wraps driver errors, so the SQLSTATE is on the cause rather than the
    exception the caller sees.
    """
    state = getattr(getattr(exc, "__cause__", None), "sqlstate", None) or getattr(exc, "sqlstate", None)
    return reason_for_sqlstate(state)


def reserve_subnet_cidrs(request: SubnetReservationRequest) -> tuple[str, ...]:
    """Reserve the requested batch and return the CIDRs in authored subnet order.

    Raises:
        SubnetCoordinationError: The reservation conflicted with an existing one
            for this request, the network is exhausted, the operation generation
            is not current, no range is bound to the request, or the routine
            rejected the request shape.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                RESERVE_SQL,
                [
                    request.contract_version,
                    request.operation_id,
                    request.request_id,
                    request.network_id,
                    request.network_cidr,
                    request.prefix_length,
                    request.subnet_count,
                    observations_as_pg_array(request.observed_cidrs),
                    request.shape_fingerprint,
                ],
            )
            rows = cursor.fetchall()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        raise SubnetCoordinationError(f"subnet reservation failed: {reason}") from None
    return parse_reservation_result(rows, expected_count=request.subnet_count)


def read_subnet_reservation(*, operation_id: str, request_id: str) -> tuple[str, ...]:
    """Return this request's existing reservation in authored subnet order.

    Returns an empty tuple when nothing is reserved; that is the legitimate state
    of a range whose provision never reached reservation.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(READ_SQL, [COORDINATION_CONTRACT_VERSION, str(operation_id), str(request_id)])
            rows = cursor.fetchall()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        raise SubnetCoordinationError(f"subnet reservation read failed: {reason}") from None
    return parse_reservation_result(rows, expected_count=len(rows))


def release_subnet_reservation(*, operation_id: str, request_id: str) -> int:
    """Release this request's owned reservations and return how many were removed.

    Idempotent: a second release returns 0. Drift-observed occupancy is never
    released -- it is evidence about the provider, not this range's to give back.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(RELEASE_SQL, [COORDINATION_CONTRACT_VERSION, str(operation_id), str(request_id)])
            row = cursor.fetchone()
    except Exception as exc:
        reason = _reason_for(exc)
        if reason is None:
            raise
        raise SubnetCoordinationError(f"subnet reservation release failed: {reason}") from None
    return int(row[0]) if row and row[0] is not None else 0
