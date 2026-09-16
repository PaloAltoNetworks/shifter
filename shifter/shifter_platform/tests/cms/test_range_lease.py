"""Behaviour tests for the shared enforced range lease lifecycle (#1696)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from cms.models import RangeInstance
from cms.models import Request as CMSRequest
from shared.enums import RangeSource, RequestType, ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()


def _range(
    user,
    *,
    source=RangeSource.MISSION_CONTROL,
    expires_at=None,
    maximum_expires_at=None,
    extension_days=None,
):
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(user).workspace_id
    request = CMSRequest.objects.create(
        workspace_id=workspace_id,
        request_id=uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )
    return RangeInstance.objects.create(
        workspace_id=workspace_id,
        user_id=user.id,
        request=request,
        status=ResourceStatus.READY.value,
        scenario_id="basic",
        range_source=source.value,
        expires_at=expires_at,
        maximum_expires_at=maximum_expires_at,
        extension_days=extension_days,
    )


def test_mission_control_lease_has_long_initial_lifetime_and_hard_limit():
    from cms.services._range_lease import build_range_lease

    now = timezone.now()
    lease = build_range_lease(RangeSource.MISSION_CONTROL, now=now)

    assert lease.expires_at == now + timedelta(days=30)
    assert lease.maximum_expires_at == now + timedelta(days=365)
    assert lease.extension_days == 30


def test_mission_control_lease_uses_the_configured_policy():
    from cms.services._range_lease import build_range_lease
    from shared.mission_control_lease import MissionControlLeasePolicy

    now = timezone.now()
    policy = MissionControlLeasePolicy(initial_days=7, extension_days=3, maximum_days=90, extensions_enabled=False)

    lease = build_range_lease(RangeSource.MISSION_CONTROL, now=now, policy=policy)

    assert lease.expires_at == now + timedelta(days=7)
    assert lease.maximum_expires_at == now + timedelta(days=90)
    assert lease.extension_days == 3


def test_mission_control_lease_reads_policy_from_settings():
    from django.test import override_settings

    from cms.services._range_lease import build_range_lease
    from shared.mission_control_lease import MissionControlLeasePolicy

    now = timezone.now()
    policy = MissionControlLeasePolicy(initial_days=14, extension_days=14, maximum_days=180)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=policy):
        lease = build_range_lease(RangeSource.MISSION_CONTROL, now=now)

    assert lease.expires_at == now + timedelta(days=14)
    assert lease.maximum_expires_at == now + timedelta(days=180)
    assert lease.extension_days == 14


def test_ctf_lease_ignores_the_mission_control_policy():
    from django.test import override_settings

    from cms.services._range_lease import build_range_lease
    from shared.mission_control_lease import MissionControlLeasePolicy

    now = timezone.now()
    cleanup_at = now + timedelta(days=5)
    policy = MissionControlLeasePolicy(initial_days=1, extension_days=1, maximum_days=1)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=policy):
        lease = build_range_lease(RangeSource.CTF, now=now, enforced_deadline=cleanup_at)

    assert lease.expires_at == cleanup_at
    assert lease.maximum_expires_at == cleanup_at
    assert lease.extension_days == 0


def test_extension_uses_the_generation_snapshot_not_the_current_policy():
    from django.test import override_settings

    from cms.services._range_lease import extend_mission_control_range
    from shared.mission_control_lease import MissionControlLeasePolicy

    user = User.objects.create_user(username="lease-snapshot@example.com")
    now = timezone.now()
    # The generation launched with a 7-day increment; a later policy raise to 99 must
    # not change how much this generation extends.
    _range(
        user,
        expires_at=now + timedelta(days=5),
        maximum_expires_at=now + timedelta(days=400),
        extension_days=7,
    )
    later_policy = MissionControlLeasePolicy(initial_days=99, extension_days=99, maximum_days=999)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=later_policy):
        projection = extend_mission_control_range(user)

    assert projection.extension_days == 7
    assert projection.expires_at == pytest.approx(now + timedelta(days=12), abs=timedelta(seconds=1))


def test_disabling_extensions_blocks_extend_and_flips_can_extend():
    from django.test import override_settings

    from cms.services._range_lease import (
        RangeLeaseConflict,
        extend_mission_control_range,
        get_mission_control_range_lease,
    )
    from shared.mission_control_lease import MissionControlLeasePolicy

    user = User.objects.create_user(username="lease-switch-off@example.com")
    now = timezone.now()
    _range(
        user,
        expires_at=now + timedelta(days=5),
        maximum_expires_at=now + timedelta(days=40),
        extension_days=30,
    )
    disabled = MissionControlLeasePolicy(extensions_enabled=False)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=disabled):
        assert get_mission_control_range_lease(user).can_extend is False
        with pytest.raises(RangeLeaseConflict, match="disabled"):
            extend_mission_control_range(user)


def test_live_group_policy_can_disable_extensions_for_an_existing_generation():
    from django.contrib.auth.models import Group

    from cms.models import MissionControlGroupLeasePolicy
    from cms.services._range_lease import (
        RangeLeaseConflict,
        extend_mission_control_range,
        get_mission_control_range_lease,
    )

    user = User.objects.create_user(username="lease-group-switch-off@example.com")
    group = Group.objects.create(name="Lease extension disabled")
    user.groups.add(group)
    now = timezone.now()
    _range(
        user,
        expires_at=now + timedelta(days=5),
        maximum_expires_at=now + timedelta(days=40),
        extension_days=30,
    )
    MissionControlGroupLeasePolicy.objects.create(
        group=group,
        initial_days=30,
        extension_days=30,
        maximum_days=365,
        extensions_enabled=False,
    )

    assert get_mission_control_range_lease(user).can_extend is False
    with pytest.raises(RangeLeaseConflict, match="disabled"):
        extend_mission_control_range(user)


def test_disabling_extensions_does_not_stop_cleanup(monkeypatch):
    from django.test import override_settings

    from cms.services._range_lease import expire_due_ranges
    from shared.mission_control_lease import MissionControlLeasePolicy

    user = User.objects.create_user(username="lease-switch-cleanup@example.com")
    now = timezone.now()
    due = _range(
        user,
        expires_at=now - timedelta(minutes=1),
        maximum_expires_at=now + timedelta(days=1),
        extension_days=30,
    )
    dispatched: list[int] = []
    monkeypatch.setattr(
        "cms.services._range_lease._dispatch_expired_range", lambda instance: dispatched.append(instance.pk)
    )
    disabled = MissionControlLeasePolicy(extensions_enabled=False)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=disabled):
        # Cleanup is policy-agnostic: turning extensions off never disables destruction.
        counts = expire_due_ranges(now=now)

    assert dispatched == [due.pk]
    assert counts == {"expired": 1, "failed": 0}


def test_ctf_lease_uses_the_enforced_event_cleanup_deadline():
    from cms.services._range_lease import build_range_lease

    now = timezone.now()
    cleanup_at = now + timedelta(days=5)

    lease = build_range_lease(RangeSource.CTF, now=now, enforced_deadline=cleanup_at)

    assert lease.expires_at == cleanup_at
    assert lease.maximum_expires_at == cleanup_at
    assert lease.extension_days == 0


def test_lease_builder_rejects_invalid_deadlines_and_sources():
    from cms.services._range_lease import RangeLeaseConflict, build_range_lease

    now = timezone.now()
    with pytest.raises(RangeLeaseConflict, match="future"):
        build_range_lease(RangeSource.CTF, now=now, enforced_deadline=now)
    unsupported_source = cast(RangeSource, object())
    with pytest.raises(RangeLeaseConflict, match="Unsupported"):
        build_range_lease(unsupported_source, now=now)


def test_extend_mission_control_range_advances_one_bounded_increment():
    from cms.services._range_lease import extend_mission_control_range
    from shared.audit import AuditAction, AuditActorType
    from shared.models import AuditLog

    user = User.objects.create_user(username="lease-owner@example.com")
    now = timezone.now()
    instance = _range(
        user,
        expires_at=now + timedelta(days=5),
        maximum_expires_at=now + timedelta(days=40),
    )

    projection = extend_mission_control_range(user)

    instance.refresh_from_db()
    assert instance.expires_at == projection.expires_at
    assert instance.expires_at == pytest.approx(now + timedelta(days=35), abs=timedelta(seconds=1))
    assert projection.can_extend is True
    audit = AuditLog.objects.get(
        entity_id=instance.pk,
        action=AuditAction.UPDATE,
        context="mission_control_range_lease_extension",
    )
    assert audit.actor_type == AuditActorType.USER
    assert audit.actor_id == user.pk
    assert audit.previous_state["expires_at"] < audit.new_state["expires_at"]


def test_membership_removal_revokes_lease_reads_and_updates():
    from cms.services._range_lease import (
        RangeLeaseNotFound,
        extend_mission_control_range,
        get_mission_control_range_lease,
    )
    from workspaces.models import WorkspaceMembership

    user = User.objects.create_user(username="lease-revoked@example.com")
    now = timezone.now()
    _range(
        user,
        expires_at=now + timedelta(days=5),
        maximum_expires_at=now + timedelta(days=40),
    )
    WorkspaceMembership.objects.filter(user=user).delete()

    assert get_mission_control_range_lease(user) is None
    with pytest.raises(RangeLeaseNotFound, match="not found"):
        extend_mission_control_range(user)


def test_extend_mission_control_range_caps_at_the_hard_deadline():
    from cms.services._range_lease import RangeLeaseConflict, extend_mission_control_range

    user = User.objects.create_user(username="lease-cap@example.com")
    now = timezone.now()
    instance = _range(
        user,
        expires_at=now + timedelta(days=20),
        maximum_expires_at=now + timedelta(days=25),
    )

    projection = extend_mission_control_range(user)
    instance.refresh_from_db()

    assert instance.expires_at == instance.maximum_expires_at
    assert projection.can_extend is False
    with pytest.raises(RangeLeaseConflict, match="maximum lifetime"):
        extend_mission_control_range(user)


def test_expired_mission_control_range_cannot_be_revived_by_extension():
    from cms.services._range_lease import RangeLeaseConflict, extend_mission_control_range

    user = User.objects.create_user(username="lease-expired@example.com")
    now = timezone.now()
    instance = _range(
        user,
        expires_at=now - timedelta(minutes=1),
        maximum_expires_at=now + timedelta(days=30),
    )

    with pytest.raises(RangeLeaseConflict, match="expired"):
        extend_mission_control_range(user)

    instance.refresh_from_db()
    assert instance.expires_at < now


def test_ctf_range_cannot_use_the_mission_control_extension_path():
    from cms.services._range_lease import RangeLeaseNotFound, extend_mission_control_range

    user = User.objects.create_user(username="ctf-lease@example.com")
    deadline = timezone.now() + timedelta(days=2)
    _range(user, source=RangeSource.CTF, expires_at=deadline, maximum_expires_at=deadline)

    with pytest.raises(RangeLeaseNotFound):
        extend_mission_control_range(user)


def test_extension_rejects_unsaved_and_unleased_ranges():
    from cms.services._range_lease import (
        RangeLeaseConflict,
        RangeLeaseNotFound,
        extend_mission_control_range,
        get_mission_control_range_lease,
    )

    unsaved_user = User()
    with pytest.raises(RangeLeaseNotFound):
        extend_mission_control_range(unsaved_user)
    assert get_mission_control_range_lease(unsaved_user) is None

    user = User.objects.create_user(username="legacy-unleased@example.com")
    _range(user)
    with pytest.raises(RangeLeaseConflict, match="unavailable"):
        extend_mission_control_range(user)


def test_projection_defensively_rejects_a_partially_missing_lease():
    from cms.services._range_lease import RangeLeaseConflict, _projection

    user = User.objects.create_user(username="partial-lease@example.com")
    instance = _range(user, expires_at=None, maximum_expires_at=None)

    with pytest.raises(RangeLeaseConflict, match="unavailable"):
        _projection(instance)


def test_expire_due_ranges_dispatches_only_due_live_rows(monkeypatch):
    from cms.services._range_lease import expire_due_ranges

    due_user = User.objects.create_user(username="due-lease@example.com")
    future_user = User.objects.create_user(username="future-lease@example.com")
    now = timezone.now()
    due = _range(due_user, expires_at=now - timedelta(minutes=1), maximum_expires_at=now + timedelta(days=1))
    future = _range(
        future_user,
        expires_at=now + timedelta(days=1),
        maximum_expires_at=now + timedelta(days=2),
    )
    dispatched: list[object] = []
    lease_transaction_depth = 0
    django_atomic = transaction.atomic

    @contextmanager
    def tracked_atomic():
        nonlocal lease_transaction_depth
        with django_atomic():
            lease_transaction_depth += 1
            try:
                yield
            finally:
                lease_transaction_depth -= 1

    def dispatch(instance):
        assert lease_transaction_depth == 1
        dispatched.append(instance.pk)

    monkeypatch.setattr("cms.services._range_lease.transaction.atomic", tracked_atomic)
    monkeypatch.setattr("cms.services._range_lease._dispatch_expired_range", dispatch)

    counts = expire_due_ranges(now=now, batch_size=10)

    assert dispatched == [due.pk]
    assert counts == {"expired": 1, "failed": 0}
    future.refresh_from_db()
    assert future.status == ResourceStatus.READY.value


def test_expire_due_ranges_uses_canonical_destroy_and_system_audit():
    from cms.services._range_lease import expire_due_ranges
    from engine.models import Range as EngineRange
    from engine.models import Request as EngineRequest
    from shared.audit import AuditAction, AuditActorType
    from shared.models import AuditLog

    user = User.objects.create_user(username="lease-cleanup@example.com")
    now = timezone.now()
    instance = _range(
        user,
        expires_at=now - timedelta(minutes=1),
        maximum_expires_at=now + timedelta(days=1),
    )
    engine_request = EngineRequest.objects.create(
        request_id=instance.request.request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    engine_range = EngineRange.objects.create(
        workspace_id=instance.workspace_id,
        request=engine_request,
        user=user,
        status=ResourceStatus.READY.value,
    )

    assert expire_due_ranges(now=now) == {"expired": 1, "failed": 0}

    instance = RangeInstance.all_objects.get(pk=instance.pk)
    engine_range.refresh_from_db()
    audit = AuditLog.objects.get(
        entity_id=instance.pk,
        action=AuditAction.DEPROVISION,
        context="range_lease_expired",
    )
    assert instance.status == ResourceStatus.DESTROYING.value
    assert instance.deleted_at is not None
    assert engine_range.status == ResourceStatus.DESTROYING.value
    assert audit.actor_type == AuditActorType.SYSTEM
    assert audit.actor_id is None


def test_expire_due_ranges_counts_a_row_without_a_request_as_failed():
    from cms.services._range_lease import expire_due_ranges
    from workspaces.services import resolve_personal_workspace

    user = User.objects.create_user(username="lease-missing-request@example.com")
    now = timezone.now()
    instance = RangeInstance.objects.create(
        workspace_id=resolve_personal_workspace(user).workspace_id,
        user_id=user.id,
        request=None,
        status=ResourceStatus.READY.value,
        scenario_id="basic",
        range_source=RangeSource.MISSION_CONTROL.value,
        expires_at=now - timedelta(minutes=1),
        maximum_expires_at=now + timedelta(days=1),
    )

    assert expire_due_ranges(now=now) == {"expired": 0, "failed": 1}
    instance.refresh_from_db()
    assert instance.status == ResourceStatus.READY.value
