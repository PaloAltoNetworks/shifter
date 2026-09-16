"""CTF domain-owned range aggregate guard (PLAT-237, #1944; ADR-046-R14, ADR-051).

A range is part of a CTF event aggregate when a CTF team holds it as its live
range, or a spare-range pool row owns it for an event. Such a range's workspace
scope is bound to the event and must not be moved independently by the Mission
Control workspace-scope administration surface. Registered into the shared
aggregate-guard seam at app startup so CMS can consult it without importing CTF
(ADR-001); membership is decided from CTF's own rows, never from a provenance
label carried on the range projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


def ctf_range_aggregate_guard(pairs: Sequence[tuple[uuid.UUID, int]]) -> set[int]:
    """Return the ``range_instance_id`` values in ``pairs`` bound to a CTF event."""
    from ctf.models import CTFParticipant, CTFSpareRange

    request_to_range = {
        request_id: range_instance_id for request_id, range_instance_id in pairs if range_instance_id is not None
    }
    range_ids = set(request_to_range.values())
    request_ids = set(request_to_range)
    if not range_ids:
        return set()

    # The model columns are nullable, so guard each row against None even though
    # an ``__in`` filter over non-null ids can only return non-null matches.
    bound: set[int] = set()
    for range_instance_id in CTFParticipant.objects.filter(range_instance_id__in=range_ids).values_list(
        "range_instance_id", flat=True
    ):
        if range_instance_id is not None:
            bound.add(range_instance_id)
    for range_instance_id in CTFSpareRange.objects.filter(range_instance_id__in=range_ids).values_list(
        "range_instance_id", flat=True
    ):
        if range_instance_id is not None:
            bound.add(range_instance_id)
    for request_id in CTFSpareRange.objects.filter(request_id__in=request_ids).values_list("request_id", flat=True):
        if request_id is None:
            continue
        range_instance_id = request_to_range.get(request_id)
        if range_instance_id is not None:
            bound.add(range_instance_id)
    return bound


def register_ctf_range_aggregate_guard() -> None:
    """Register the CTF aggregate guard with the shared seam (idempotent)."""
    from shared.range_workspace_aggregate import register_range_aggregate_guard

    register_range_aggregate_guard(ctf_range_aggregate_guard)
