"""PostgreSQL proofs that quota enforcement serializes on the workspace mutex.

An enforcing hard cap must hold under real row-lock contention: two concurrent
admissions for the same workspace cannot both slip past the same limit. SQLite
cannot prove ``select_for_update`` semantics, so these run only on the Postgres
lane.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from workspaces import services
from workspaces.models import (
    QUOTA_MODE_ENFORCING,
    QUOTA_RESOURCE_CONCURRENT_RANGES,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Organization,
    Workspace,
    WorkspaceMembership,
    WorkspaceQuotaPolicy,
    WorkspaceQuotaReservation,
)
from workspaces.roles import WorkspaceRole

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
User = get_user_model()


def _reserve(workspace_id, key, actor_id, barrier):
    barrier.wait(timeout=10)
    audit = services.WorkspaceQuotaAuditContext(actor_type="user", actor_id=actor_id)
    try:
        with transaction.atomic():
            verdict = services.reserve_workspace_concurrent_range(workspace_id, key, audit)
        return ("ok", verdict.outcome)
    except services.WorkspaceQuotaRejected:
        return ("rejected", None)
    finally:
        connection.close()


def test_concurrent_range_reservations_cannot_exceed_a_hard_cap():
    workspace = Workspace.objects.create(organization=Organization.objects.create(name="Race Lab"), name="Race WS")
    owner = User.objects.create_user(username="q-owner@example.com", email="q-owner@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    WorkspaceQuotaPolicy.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, limit=1, mode=QUOTA_MODE_ENFORCING
    )
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda i: _reserve(workspace.pk, f"corr-{i}", owner.pk, barrier),
                range(2),
            )
        )

    assert sorted(result[0] for result in outcomes) == ["ok", "rejected"]
    assert (
        WorkspaceQuotaReservation.objects.filter(
            workspace=workspace, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, released_at__isnull=True
        ).count()
        == 1
    )


def _add_member(workspace_uuid, owner_id, target_email, barrier):
    barrier.wait(timeout=10)
    owner = User.objects.get(pk=owner_id)
    audit = services.MembershipAuditContext(actor_type="user", actor_id=owner_id)
    try:
        services.add_workspace_member(owner, workspace_uuid, target_email, WorkspaceRole.MEMBER.value, audit=audit)
        return "ok"
    except services.WorkspaceMembershipError as exc:
        return exc.code
    finally:
        connection.close()


def test_concurrent_member_adds_cannot_exceed_a_seat_hard_cap():
    workspace = Workspace.objects.create(organization=Organization.objects.create(name="Seat Lab"), name="Seat WS")
    owner = User.objects.create_user(username="s-owner@example.com", email="s-owner@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    # One free seat beyond the owner; two concurrent adds must fill exactly one.
    WorkspaceQuotaPolicy.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS, limit=2, mode=QUOTA_MODE_ENFORCING
    )
    targets = [User.objects.create_user(username=f"s-t{i}@example.com", email=f"s-t{i}@example.com") for i in range(2)]
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda t: _add_member(workspace.uuid, owner.pk, t.email, barrier),
                targets,
            )
        )

    assert sorted(outcomes) == ["ok", "workspace_member_seats_exhausted"]
    assert WorkspaceMembership.objects.filter(workspace=workspace).count() == 2  # owner + exactly one member
