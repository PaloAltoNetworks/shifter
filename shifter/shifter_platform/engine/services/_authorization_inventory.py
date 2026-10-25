"""SQL-authoritative range inventory for authorization delegation proofs."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from shared.authorization import TargetRef, bind_authorization_descendant_resolver


def list_authorization_range_uuids(workspace_ids: Sequence[int], limit: int) -> tuple[UUID, ...]:
    """Return at most ``limit`` range UUIDs for the exact workspace ids."""
    from engine.models import Range

    if limit <= 0 or not workspace_ids:
        return ()
    return tuple(
        Range.objects.filter(workspace_id__in=workspace_ids).order_by("uuid").values_list("uuid", flat=True)[:limit]
    )


def _authorization_range_targets(workspace_ids: Sequence[int], limit: int) -> tuple[TargetRef, ...]:
    """Project SQL-owned range identities into neutral authorization targets."""
    return tuple(TargetRef("range", item) for item in list_authorization_range_uuids(workspace_ids, limit))


def register_authorization_range_inventory() -> None:
    """Bind the Engine-owned SQL range inventory to the neutral port."""
    bind_authorization_descendant_resolver("engine.ranges", _authorization_range_targets)
