"""Read-only queries: return dicts/shared-schema projections, not model instances."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from shared.schemas.app import LinkedRangeContext


def get_authoritative_range_status(
    *,
    request_id: UUID | str | None = None,
    range_id: int | None = None,
) -> str | None:
    """Return the authoritative ``engine.Range.status`` for the given correlation key.

    Prefers ``request_id`` (new pattern) over ``range_id`` (legacy).  Returns
    ``None`` when no matching Range row exists.

    This is the canonical seam for cross-layer status reconciliation: CMS and
    other consumers must use this function instead of importing engine.models
    directly (ADR-001-R2).

    Args:
        request_id: UUID that links an engine Request to a CMS Request.
        range_id: Engine Range PK (legacy, used when request_id is absent).

    Returns:
        Status string (a ``shared.enums.ResourceStatus`` value) or ``None``.
    """
    from engine.models import Range

    if request_id is not None:
        eng = Range.objects.filter(request__request_id=request_id).first()
        if eng is not None:
            return eng.status

    if range_id is not None:
        eng = Range.objects.filter(pk=range_id).first()
        if eng is not None:
            return eng.status

    return None


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


def get_ranges_for_ngfw(user_id: int, ngfw_request_id: UUID | str) -> list[LinkedRangeContext]:
    """Get active ranges linked to an NGFW, identified by its request_id.

    The NGFW is identified by ``ngfw_request_id`` — the provisioning Request UUID
    that the CMS and Engine share as their cross-layer correlation key. The
    Engine NGFW ``Instance`` is resolved from that request_id; ranges are linked
    to it via ``Range.ngfw_instance``. (Callers in other layers hold the CMS
    NGFW's request_id, not the Engine Instance's integer pk, so taking the
    correlation key keeps the Engine's internal ids out of the upper layers.)

    Returns a list of ``LinkedRangeContext`` projections (the shared schema the
    NGFW templates render) for each linked range. An unknown/unprovisioned NGFW
    yields an empty list.
    """
    from engine.models import Instance, Range
    from shared.schemas.app import LinkedRangeContext

    ngfw_instance = Instance.objects.filter(
        request__request_id=ngfw_request_id,
        role=Instance.Role.NGFW,
    ).first()
    if ngfw_instance is None:
        return []

    ranges = Range.objects.filter(
        ngfw_instance=ngfw_instance,
        user_id=user_id,
        destroyed_at__isnull=True,
    ).order_by("-created_at")

    return [LinkedRangeContext(range_id=r.pk, status=r.status, created_at=r.created_at) for r in ranges]
