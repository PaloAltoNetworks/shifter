"""Bounded Engine-owned projection used by the CMS offboarding boundary."""

from dataclasses import dataclass
from uuid import UUID

from ._range_by_request import RangeProjectionIntegrityError


@dataclass(frozen=True, slots=True)
class RangeOwnershipProjection:
    """Immutable SQL identity/ancestry; no range configuration or access data."""

    uuid: UUID
    user_id: int
    request_user_id: int
    cms_user_id: int | None
    scope_kind: str
    account_id: int | None
    organization_id: int | None
    workspace_id: int | None


def range_ownership_projection(request_id: UUID) -> RangeOwnershipProjection | None:
    """Fail closed on duplicate correlation instead of choosing an Engine row."""
    from engine.models import Range

    rows = tuple(Range.objects.select_related("request").filter(request__request_id=request_id)[:2])
    if len(rows) > 1:
        raise RangeProjectionIntegrityError("Range ownership projection unavailable")
    if not rows or rows[0].request is None:
        return None
    row = rows[0]
    request = row.request
    if request is None:
        return None
    return RangeOwnershipProjection(
        row.uuid,
        row.user_id,
        request.user_id,
        row.cms_user_id,
        row.scope_kind,
        row.account_id,
        row.organization_id,
        row.workspace_id,
    )
