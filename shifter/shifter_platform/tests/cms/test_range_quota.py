"""Concurrent-range quota enforcement at the CMS launch seam (PLAT-239, #1946).

Drives the real reservation seam and the convergent status handler against real
rows (no first-party seam patched, per ADR-019). Each test asks the launch path a
question a caller would ask and asserts the effect (reserved / blocked / released),
so it goes red if the enforcement is removed. The threaded PostgreSQL race is
proven in ``test_range_quota_concurrency_postgres``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from cms.exceptions import WorkspaceLaunchQuotaExceeded
from cms.handlers.range_events import apply_range_status
from cms.models import RangeInstance, Request
from cms.services._range_launch_common import _reserve_active_range_slot
from shared.enums import RangeSource, ResourceStatus
from workspaces import services
from workspaces.models import (
    QUOTA_MODE_ADVISORY,
    QUOTA_MODE_ENFORCING,
    QUOTA_OUTCOME_REJECTED,
    QUOTA_RESOURCE_CONCURRENT_RANGES,
    WorkspaceQuotaDecision,
    WorkspaceQuotaPolicy,
    WorkspaceQuotaReservation,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-quota@example.com", email="cms-quota@example.com")


def _workspace_id(user):
    return services.resolve_personal_workspace(user).workspace_id


def _set_policy(workspace_id, limit, mode):
    WorkspaceQuotaPolicy.objects.create(
        workspace_id=workspace_id, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, limit=limit, mode=mode
    )


def _make_persist(user, workspace_id, source=RangeSource.MISSION_CONTROL):
    def _persist(cms_request):
        return RangeInstance.objects.create(
            workspace_id=workspace_id,
            request=cms_request,
            scenario_id="basic",
            user_id=user.id,
            range_source=source.value,
        )

    return _persist


def _audit(user):
    return services.WorkspaceQuotaAuditContext(actor_type="user", actor_id=user.id)


def test_reserve_at_launch_creates_open_reservation(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 2, QUOTA_MODE_ENFORCING)

    correlation_id, _request, _instance, _egress = _reserve_active_range_slot(
        user, RangeSource.MISSION_CONTROL, _make_persist(user, workspace_id), workspace_id
    )

    assert WorkspaceQuotaReservation.objects.filter(
        workspace_id=workspace_id, correlation_key=str(correlation_id), released_at__isnull=True
    ).exists()


def test_enforcing_cap_blocks_launch_and_leaves_no_orphan(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 1, QUOTA_MODE_ENFORCING)
    # Pre-consume the only slot with a standalone reservation (no active range),
    # so the launch is blocked purely by the quota, not the active-range rule.
    services.reserve_workspace_concurrent_range(workspace_id, "seed-corr", _audit(user))
    requests_before = Request.objects.filter(user=user).count()
    persist = _make_persist(user, workspace_id)

    with pytest.raises(WorkspaceLaunchQuotaExceeded):
        _reserve_active_range_slot(user, RangeSource.MISSION_CONTROL, persist, workspace_id)

    # No range/request persisted; the rejection is recorded as durable evidence.
    assert Request.objects.filter(user=user).count() == requests_before
    assert not RangeInstance.objects.filter(user_id=user.id).exists()
    assert WorkspaceQuotaDecision.objects.filter(
        workspace_id=workspace_id, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, outcome=QUOTA_OUTCOME_REJECTED
    ).exists()


def test_active_range_collision_rolls_back_the_quota_reservation(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 5, QUOTA_MODE_ENFORCING)
    persist = _make_persist(user, workspace_id)

    # First launch takes the (user, MISSION_CONTROL) active-range slot + one reservation.
    _reserve_active_range_slot(user, RangeSource.MISSION_CONTROL, persist, workspace_id)
    # A second same-source launch collides on the active-range constraint; the whole
    # atomic rolls back, so its tentative quota reservation is not left behind.
    from cms.exceptions import CMSError

    with pytest.raises(CMSError):
        _reserve_active_range_slot(user, RangeSource.MISSION_CONTROL, persist, workspace_id)

    assert (
        WorkspaceQuotaReservation.objects.filter(
            workspace_id=workspace_id, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, released_at__isnull=True
        ).count()
        == 1
    )


def test_advisory_cap_admits_launch_with_a_warning(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 1, QUOTA_MODE_ADVISORY)
    services.reserve_workspace_concurrent_range(workspace_id, "seed-corr", _audit(user))

    correlation_id, _request, _instance, _egress = _reserve_active_range_slot(
        user, RangeSource.MISSION_CONTROL, _make_persist(user, workspace_id), workspace_id
    )

    assert WorkspaceQuotaReservation.objects.filter(
        workspace_id=workspace_id, correlation_key=str(correlation_id), released_at__isnull=True
    ).exists()
    assert RangeInstance.objects.filter(user_id=user.id).count() == 1


def test_dispatch_failure_releases_the_reservation(user, make_agent, hydratable_scenario, monkeypatch):
    from cms import services as cms_services

    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 5, QUOTA_MODE_ENFORCING)
    agent = make_agent(user)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("dispatch exploded")

    monkeypatch.setattr("cms.services._raes_range_create._dispatch_raes_package", _boom)

    with pytest.raises(RuntimeError, match="dispatch exploded"):
        cms_services.create_range(user, hydratable_scenario.scenario_id, {"windows": agent.id})

    instance = RangeInstance.all_objects.get(user_id=user.id)
    assert instance.status == ResourceStatus.FAILED.value
    # The FAILED transition and the release commit together, so no open
    # reservation leaks when no terminal status event will ever arrive.
    assert not WorkspaceQuotaReservation.objects.filter(
        workspace_id=workspace_id, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, released_at__isnull=True
    ).exists()


def test_terminal_status_releases_the_reservation(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 5, QUOTA_MODE_ENFORCING)
    correlation_id, _request, instance, _egress = _reserve_active_range_slot(
        user, RangeSource.MISSION_CONTROL, _make_persist(user, workspace_id), workspace_id
    )

    apply_range_status(instance, ResourceStatus.DESTROYED.value)

    reservation = WorkspaceQuotaReservation.objects.get(workspace_id=workspace_id, correlation_key=str(correlation_id))
    assert reservation.released_at is not None


def test_non_terminal_status_does_not_release_the_reservation(user):
    workspace_id = _workspace_id(user)
    _set_policy(workspace_id, 5, QUOTA_MODE_ENFORCING)
    correlation_id, _request, instance, _egress = _reserve_active_range_slot(
        user, RangeSource.MISSION_CONTROL, _make_persist(user, workspace_id), workspace_id
    )

    apply_range_status(instance, ResourceStatus.READY.value)

    reservation = WorkspaceQuotaReservation.objects.get(workspace_id=workspace_id, correlation_key=str(correlation_id))
    assert reservation.released_at is None
