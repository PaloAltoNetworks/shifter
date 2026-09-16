"""Tests for the CMS user-offboarding transfer orchestrator (PLAT-236, #1943).

``cms.services.transfer_user_ownership`` is the single cross-domain command the
composition-root Administer view calls. These tests drive it against real
``RangeInstance`` / ``Request`` rows and the real ``reassign_range_owner``
authority (no first-party seam is mocked, per ADR-019-R1): a range whose new
owner is not a member of its workspace is reported blocked, and soft-deleted
ranges are excluded. The workspace-transfer path is covered in
``tests/workspaces/test_admin_transfer_ownership.py`` and the HTTP contract in
``tests/config/test_administer_transfer_ownership.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.models import RangeInstance, Request
from cms.services import OffboardingAuditContext, transfer_user_ownership
from shared.enums import RangeSource, RequestType, ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()


def _make_user(username: str) -> User:
    return User.objects.create_user(username=username, email=f"{username}@example.com")


def _personal_ws(user: User) -> int:
    from workspaces.services import resolve_personal_workspace

    return resolve_personal_workspace(user).workspace_id


def _range(user: User, *, source: str = RangeSource.MISSION_CONTROL.value, deleted: bool = False) -> RangeInstance:
    workspace_id = _personal_ws(user)
    request = Request.objects.create(
        workspace_id=workspace_id, request_id=uuid4(), request_type=RequestType.RANGE.value, user=user
    )
    # A terminal status auto-sets deleted_at in save(), so a "deleted" range is
    # inserted already soft-deleted and never collides with the partial unique
    # constraint on active (user_id, range_source).
    status = ResourceStatus.DESTROYED.value if deleted else ResourceStatus.READY.value
    return RangeInstance.objects.create(
        workspace_id=workspace_id,
        user_id=user.id,
        scenario_id="basic",
        status=status,
        range_source=source,
        request=request,
    )


def test_unknown_kind_raises():
    source, replacement = _make_user("s"), _make_user("r")
    audit = OffboardingAuditContext(actor_type="user", actor_id=1)
    with pytest.raises(ValueError):
        transfer_user_ownership(source, replacement, kinds=["credentials"], audit=audit)


def test_range_blocked_when_replacement_not_a_member():
    # The range lives in the source's personal workspace; the replacement is not a
    # member, so reassign_range_owner refuses and the orchestrator reports it
    # blocked rather than forcing or silently rehoming it.
    source, replacement, actor = _make_user("s"), _make_user("r"), _make_user("a")
    _range(source)

    summary = transfer_user_ownership(
        source, replacement, kinds=["ranges"], audit=OffboardingAuditContext(actor_type="user", actor_id=actor.id)
    )

    assert summary.ranges_reassigned == 0
    assert summary.ranges_blocked == 1
    # Ownership did not move.
    assert RangeInstance.objects.filter(user_id=source.id, deleted_at__isnull=True).count() == 1


def test_deleted_ranges_excluded():
    source, replacement, actor = _make_user("s"), _make_user("r"), _make_user("a")
    _range(source, deleted=True)

    summary = transfer_user_ownership(
        source, replacement, kinds=["ranges"], audit=OffboardingAuditContext(actor_type="user", actor_id=actor.id)
    )

    assert summary.ranges_reassigned == 0
    assert summary.ranges_blocked == 0
