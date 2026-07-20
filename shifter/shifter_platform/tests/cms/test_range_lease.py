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


def _range(user, *, source=RangeSource.MISSION_CONTROL, expires_at=None, maximum_expires_at=None):
    request = CMSRequest.objects.create(
        request_id=uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )
    return RangeInstance.objects.create(
        user_id=user.id,
        request=request,
        status=ResourceStatus.READY.value,
        scenario_id="basic",
        range_source=source.value,
        expires_at=expires_at,
        maximum_expires_at=maximum_expires_at,
    )


def test_mission_control_lease_has_long_initial_lifetime_and_hard_limit():
    from cms.services._range_lease import build_range_lease

    now = timezone.now()
    lease = build_range_lease(RangeSource.MISSION_CONTROL, now=now)

    assert lease.expires_at == now + timedelta(days=30)
    assert lease.maximum_expires_at == now + timedelta(days=365)
    assert lease.extension_days == 30


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
    from risk_register.models import AuditLog
    from shared.audit import AuditAction, AuditActorType

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
    from risk_register.models import AuditLog
    from shared.audit import AuditAction, AuditActorType

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

    user = User.objects.create_user(username="lease-missing-request@example.com")
    now = timezone.now()
    instance = RangeInstance.objects.create(
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
