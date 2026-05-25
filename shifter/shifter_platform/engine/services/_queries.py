"""Read-only queries: return dicts, not model instances."""

from __future__ import annotations

from typing import Any


def get_user_ready_range_instances(user_id: int) -> list[dict[str, Any]]:
    """Get provisioned instances for a user's active ready range.

    Returns a list of instance dicts from the range's
    ``provisioned_instances``, or an empty list if no ready range exists.
    """
    from engine.models import Range

    range_obj = Range.objects.filter(user_id=user_id, status="ready").first()
    if not range_obj or not range_obj.provisioned_instances:
        return []
    return list(range_obj.provisioned_instances)


def get_ranges_for_ngfw(user_id: int, ngfw_instance_id: int) -> list[dict[str, Any]]:
    """Get active ranges linked to an NGFW instance.

    Returns a list of dicts with ``range_id``, ``request_id``, ``status``,
    and ``created_at`` for each linked range.
    """
    from engine.models import Range

    ranges = Range.objects.filter(
        ngfw_instance_id=ngfw_instance_id,
        user_id=user_id,
        destroyed_at__isnull=True,
    ).order_by("-created_at")

    return [
        {
            "range_id": r.pk,
            "request_id": str(r.request_id) if r.request_id else None,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in ranges
    ]
