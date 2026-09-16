"""Behavior tests for the expected-source compare-and-set workspace rebind (#1944).

``engine.services.rebind_range_workspace_by_request`` moves the Engine range's
scalar ``workspace_id`` only when the persisted binding matches the source the
CMS owner expects. DB-backed per ADR-019: no patching of first-party engine
seams -- the outcomes are driven by real ``engine.Range`` rows.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from engine.services import (
    RangeProjectionIntegrityError,
    RangeWorkspaceRebindOutcome,
    rebind_range_workspace_by_request,
)
from shared.enums import RequestType

pytestmark = pytest.mark.django_db

User = get_user_model()

_SOURCE_WORKSPACE_ID = 100
_TARGET_WORKSPACE_ID = 200
_OTHER_WORKSPACE_ID = 300


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="rebind-owner@example.com", email="rebind-owner@example.com")


def _make_engine_range(*, owner, workspace_id: int, request_id=None) -> EngineRange:
    """A real engine ``Range`` (+ ``Request``) scoped to ``workspace_id``."""
    request_id = request_id or uuid4()
    engine_request = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=owner
    )
    return EngineRange.objects.create(
        workspace_id=workspace_id,
        uuid=uuid4(),
        user=owner,
        request=engine_request,
        cms_user_id=owner.id,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
    )


class TestRebindRangeWorkspaceCompareAndSet:
    def test_updates_when_binding_matches_expected_source(self, owner):
        rng = _make_engine_range(owner=owner, workspace_id=_SOURCE_WORKSPACE_ID)
        request_id = rng.request.request_id

        with transaction.atomic():
            outcome = rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )

        assert outcome is RangeWorkspaceRebindOutcome.UPDATED
        rng.refresh_from_db()
        assert rng.workspace_id == _TARGET_WORKSPACE_ID

    def test_updates_change_only_workspace_id(self, owner):
        rng = _make_engine_range(owner=owner, workspace_id=_SOURCE_WORKSPACE_ID)
        request_id = rng.request.request_id
        original_status = rng.status
        original_user_id = rng.user_id

        with transaction.atomic():
            rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )

        rng.refresh_from_db()
        assert rng.workspace_id == _TARGET_WORKSPACE_ID
        assert rng.status == original_status
        assert rng.user_id == original_user_id

    def test_idempotent_no_op_when_already_at_target(self, owner):
        rng = _make_engine_range(owner=owner, workspace_id=_TARGET_WORKSPACE_ID)
        request_id = rng.request.request_id

        with transaction.atomic():
            outcome = rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )

        assert outcome is RangeWorkspaceRebindOutcome.UNCHANGED
        rng.refresh_from_db()
        assert rng.workspace_id == _TARGET_WORKSPACE_ID

    def test_returns_not_found_when_no_engine_range(self, owner):
        with transaction.atomic():
            outcome = rebind_range_workspace_by_request(
                uuid4(),
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )

        assert outcome is RangeWorkspaceRebindOutcome.NOT_FOUND

    def test_source_mismatch_leaves_binding_untouched(self, owner):
        rng = _make_engine_range(owner=owner, workspace_id=_OTHER_WORKSPACE_ID)
        request_id = rng.request.request_id

        with transaction.atomic():
            outcome = rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )

        assert outcome is RangeWorkspaceRebindOutcome.SOURCE_MISMATCH
        rng.refresh_from_db()
        assert rng.workspace_id == _OTHER_WORKSPACE_ID

    def test_duplicate_projection_is_an_integrity_error(self, owner):
        request_id = uuid4()
        rng = _make_engine_range(owner=owner, workspace_id=_SOURCE_WORKSPACE_ID, request_id=request_id)
        # A second engine range correlated to the same request violates the
        # one-to-one invariant; the CAS refuses to guess which to move.
        second_owner = User.objects.create_user(username="rebind-owner2@example.com", email="rebind-owner2@example.com")
        EngineRange.objects.create(
            workspace_id=_SOURCE_WORKSPACE_ID,
            uuid=uuid4(),
            user=second_owner,
            request=rng.request,
            cms_user_id=second_owner.id,
            status=EngineRange.Status.READY,
            subnet_index=EngineRange.allocate_subnet_index(),
        )

        with pytest.raises(RangeProjectionIntegrityError), transaction.atomic():
            rebind_range_workspace_by_request(
                request_id,
                expected_workspace_id=_SOURCE_WORKSPACE_ID,
                new_workspace_id=_TARGET_WORKSPACE_ID,
            )
