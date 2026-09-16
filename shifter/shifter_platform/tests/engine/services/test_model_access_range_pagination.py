"""Bounded pagination for automatic model-access range assessments."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range
from engine.services import resolve_model_access_range_page, resolve_model_access_range_views

pytestmark = pytest.mark.django_db(transaction=True)
User = get_user_model()


def test_automatic_range_assessment_pages_beyond_explicit_id_limit():
    owner = User.objects.create_user("range-pagination@test")
    Range.objects.bulk_create([Range(user=owner, workspace_id=1, status=Range.Status.READY) for _ in range(1001)])

    first = resolve_model_access_range_page(all_ranges=True, page_size=1000)
    second = resolve_model_access_range_page(
        all_ranges=True,
        page_size=1000,
        continuation=first.continuation,
    )

    assert len(first.items) == 1000
    assert first.assessment_count == 1001
    assert first.continuation == first.items[-1].range_uuid
    assert len(second.items) == 1
    assert second.assessment_count == 1001
    assert second.continuation is None

    complete = resolve_model_access_range_views(all_ranges=True)
    assert len(complete) == 1001
    assert len({item.range_uuid for item in complete}) == 1001


def test_automatic_owner_expansions_are_not_treated_as_explicit_selector_ids():
    owner = User.objects.create_user("expanded-owner-pagination@test")
    range_obj = Range.objects.create(user=owner, workspace_id=1, status=Range.Status.READY)

    users = resolve_model_access_range_page(user_ids=tuple(range(owner.pk, owner.pk + 1001)))
    workspaces = resolve_model_access_range_page(workspace_ids=tuple(range(1, 1002)))

    assert [item.range_uuid for item in users.items] == [range_obj.uuid]
    assert [item.range_uuid for item in workspaces.items] == [range_obj.uuid]
