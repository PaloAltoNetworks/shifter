"""Bounded Engine range queries for model-access selector owners."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction

from shared.model_access import ModelAccessRangePage, ModelAccessRangeView, OwnedReference

from ._sharing_persistence import SharingError

_RANGE_RESOLUTION_SHAPE = "sharing.range_resolution_shape"
_RANGE_MEMBERSHIP_CHANGED = "sharing.range_membership_changed"


def _query_shape(
    *,
    range_uuids: tuple[UUID, ...] | None,
    request_uuids: tuple[UUID, ...] | None,
    user_ids: tuple[int, ...] | None,
    workspace_ids: tuple[int, ...] | None,
    all_ranges: bool,
) -> tuple[tuple[object, ...], tuple[object, ...] | None, dict[str, object]]:
    """Validate one query mode and return its supplied values and ORM filters."""
    modes = (range_uuids, request_uuids, user_ids, workspace_ids)
    if sum(value is not None for value in modes) + int(all_ranges) != 1:
        raise SharingError(_RANGE_RESOLUTION_SHAPE)

    explicit_values: tuple[object, ...] | None = None
    filters: dict[str, object] = {}
    if range_uuids is not None:
        explicit_values = tuple(range_uuids)
        filters["uuid__in"] = explicit_values
    elif request_uuids is not None:
        explicit_values = tuple(request_uuids)
        filters["request__request_id__in"] = explicit_values
    elif user_ids is not None:
        filters["user_id__in"] = tuple(user_ids)
    elif workspace_ids is not None:
        filters["workspace_id__in"] = tuple(workspace_ids)
    supplied = next((value for value in modes if value is not None), ())
    return supplied, explicit_values, filters


def _validate_supplied_values(supplied: tuple[object, ...], explicit_values: tuple[object, ...] | None) -> None:
    """Reject duplicate, overlong explicit, or boolean identifiers."""
    invalid = (
        len(supplied) != len(set(supplied))
        or (explicit_values is not None and len(supplied) > 1000)
        or any(isinstance(value, bool) for value in supplied)
    )
    if invalid:
        raise SharingError(_RANGE_RESOLUTION_SHAPE)


def _validate_page_shape(
    *, page_size: int, continuation: UUID | None, explicit_values: tuple[object, ...] | None
) -> None:
    """Validate page bounds and the explicit-query pagination prohibition."""
    invalid = (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 1000
        or (continuation is not None and not isinstance(continuation, UUID))
        or (explicit_values is not None and continuation is not None)
        or (explicit_values is not None and page_size < len(explicit_values))
    )
    if invalid:
        raise SharingError(_RANGE_RESOLUTION_SHAPE)


def resolve_model_access_range_page(
    *,
    range_uuids: tuple[UUID, ...] | None = None,
    request_uuids: tuple[UUID, ...] | None = None,
    user_ids: tuple[int, ...] | None = None,
    workspace_ids: tuple[int, ...] | None = None,
    all_ranges: bool = False,
    continuation: UUID | None = None,
    page_size: int = 1000,
) -> ModelAccessRangePage:
    """Lock one bounded keyset page from an exact range-membership query.

    Explicit identity queries are exact: an unknown or terminal range makes the
    whole resolution fail closed. Automatic collections expose an assessment
    count and continuation so deployment growth never turns into a hard result
    ceiling. Collection queries may legitimately resolve to an empty set.
    """
    from engine.models import Range

    supplied, explicit_values, filters = _query_shape(
        range_uuids=range_uuids,
        request_uuids=request_uuids,
        user_ids=user_ids,
        workspace_ids=workspace_ids,
        all_ranges=all_ranges,
    )
    _validate_supplied_values(supplied, explicit_values)
    _validate_page_shape(page_size=page_size, continuation=continuation, explicit_values=explicit_values)

    unavailable = (Range.Status.DESTROYING, Range.Status.DESTROYED, Range.Status.FAILED)
    with transaction.atomic():
        eligible = Range.objects.filter(**filters).exclude(status__in=unavailable)
        assessment_count = eligible.count()
        if continuation is not None:
            eligible = eligible.filter(uuid__gt=continuation)
        page_rows = tuple(
            eligible.select_for_update(of=("self",)).select_related("request").order_by("uuid")[: page_size + 1]
        )
        if explicit_values is not None and assessment_count != len(explicit_values):
            raise SharingError("sharing.range_membership_unavailable")
        rows = page_rows[:page_size]
        items = tuple(
            ModelAccessRangeView(
                range_ref=OwnedReference(owner="deployment", reference=f"range:{row.uuid}"),
                authority_ref=OwnedReference(owner="engine", reference=f"range:{row.uuid}"),
                range_uuid=row.uuid,
                owner_user_id=row.user_id,
                workspace_id=row.workspace_id,
                request_uuid=row.request.request_id if row.request is not None else None,
            )
            for row in rows
        )
        return ModelAccessRangePage(
            items=items,
            assessment_count=assessment_count,
            continuation=items[-1].range_uuid if len(page_rows) > page_size else None,
        )


def resolve_model_access_range_views(
    *,
    range_uuids: tuple[UUID, ...] | None = None,
    request_uuids: tuple[UUID, ...] | None = None,
    user_ids: tuple[int, ...] | None = None,
    workspace_ids: tuple[int, ...] | None = None,
    all_ranges: bool = False,
) -> tuple[ModelAccessRangeView, ...]:
    """Resolve a complete collection through stable bounded keyset pages."""
    items: list[ModelAccessRangeView] = []
    continuation = None
    assessment_count = None
    while True:
        page = resolve_model_access_range_page(
            range_uuids=range_uuids,
            request_uuids=request_uuids,
            user_ids=user_ids,
            workspace_ids=workspace_ids,
            all_ranges=all_ranges,
            continuation=continuation,
        )
        if assessment_count is None:
            assessment_count = page.assessment_count
        elif page.assessment_count != assessment_count:
            raise SharingError(_RANGE_MEMBERSHIP_CHANGED)
        items.extend(page.items)
        if page.continuation is None:
            break
        if continuation == page.continuation:
            raise SharingError(_RANGE_MEMBERSHIP_CHANGED)
        continuation = page.continuation
    if len(items) != assessment_count:
        raise SharingError(_RANGE_MEMBERSHIP_CHANGED)
    return tuple(items)
