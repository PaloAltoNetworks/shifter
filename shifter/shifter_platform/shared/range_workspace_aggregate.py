"""Pluggable domain-owned aggregate guard for range workspace-scope moves.

A range may belong to an immutable domain-owned workspace aggregate -- an
ADR-051 CTF event, or a future domain aggregate. Such a range's workspace scope
is owned by that aggregate and must not be moved independently by the Mission
Control workspace-scope administration surface (PLAT-237, #1944; ADR-046-R14).

CMS owns the rebind command but must not import a domain app to learn aggregate
membership (ADR-001). This seam mirrors :mod:`shared.range_visibility`: each
aggregate-owning domain registers one guard at app startup, and CMS consults the
union through :func:`range_instance_ids_in_domain_aggregates`.

Membership is decided authoritatively by the registered guards, never by a
range's provenance label. The seam fails CLOSED: a guard that raises is treated
as "cannot establish absence", so its candidate ranges are reported as
aggregate-bound rather than released. With no guard registered, no domain owns
aggregates, so nothing is bound.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

logger = logging.getLogger(__name__)

# Guard contract: given (request_id, range_instance_id) pairs, return the subset
# of range_instance_ids the domain owns in an immutable aggregate.
RangeAggregateGuard = Callable[[Sequence[tuple["uuid.UUID", int]]], "Iterable[int]"]

_guards: list[RangeAggregateGuard] = []


def register_range_aggregate_guard(guard: RangeAggregateGuard) -> None:
    """Register a domain aggregate guard (idempotent by identity)."""
    if not callable(guard):
        raise TypeError("guard must be callable")
    if guard not in _guards:
        _guards.append(guard)


def range_instance_ids_in_domain_aggregates(pairs: Iterable[tuple[uuid.UUID, int]]) -> set[int]:
    """Return the ``range_instance_id`` values in ``pairs`` bound to a domain aggregate.

    Unions every registered guard. Fails closed: if a guard raises, every
    candidate range it was asked about is reported bound, because the guard's
    domain could not establish absence.
    """
    materialized = [
        (request_id, range_instance_id) for request_id, range_instance_id in pairs if range_instance_id is not None
    ]
    if not materialized:
        return set()
    bound: set[int] = set()
    for guard in _guards:
        try:
            bound.update(int(range_instance_id) for range_instance_id in guard(materialized))
        except Exception:
            logger.exception("range aggregate guard failed; failing closed for its candidate ranges")
            bound.update(range_instance_id for _, range_instance_id in materialized)
    return bound


def range_in_domain_aggregate(request_id: uuid.UUID, range_instance_id: int) -> bool:
    """Return whether a single range is bound to a domain-owned aggregate."""
    return range_instance_id in range_instance_ids_in_domain_aggregates([(request_id, range_instance_id)])
