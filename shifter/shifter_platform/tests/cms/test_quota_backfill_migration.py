"""Unit tests for the concurrent-range quota reservation backfill (PLAT-239, #1946).

Drives the migration's forward function directly against the current models (the
same ``importlib`` pattern as the #1325 backfill tests). Non-terminal ranges are
never soft-deleted, so a status filter over the current manager is equivalent to
the unfiltered historical manager the real migration uses.
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model

from cms.models import RangeInstance, Request
from workspaces.models import (
    QUOTA_RESOURCE_CONCURRENT_RANGES,
    Organization,
    Workspace,
    WorkspaceQuotaReservation,
)

_BACKFILL = importlib.import_module("cms.migrations.0043_backfill_workspace_quota_reservations")

pytestmark = pytest.mark.django_db
User = get_user_model()


def _range(workspace, status, *, request_workspace_id=None):
    owner = User.objects.create_user(
        username=f"bf-{uuid.uuid4().hex[:10]}@e.com", email=f"bf-{uuid.uuid4().hex[:10]}@e.com"
    )
    request = Request.objects.create(
        request_id=uuid.uuid4(),
        request_type="range",
        user=owner,
        workspace_id=request_workspace_id if request_workspace_id is not None else workspace.pk,
    )
    RangeInstance.objects.create(
        request=request,
        scenario_id="basic",
        user_id=owner.id,
        status=status,
        workspace_id=workspace.pk,
    )
    return request


def _workspace(name="BF WS"):
    return Workspace.objects.create(organization=Organization.objects.create(name=name), name=name)


def test_backfill_reserves_live_ranges_and_skips_terminal_ones():
    workspace = _workspace()
    ready = _range(workspace, "ready")
    provisioning = _range(workspace, "provisioning")
    destroying = _range(workspace, "destroying")  # still holds provider resources
    _range(workspace, "destroyed")
    _range(workspace, "failed")

    _BACKFILL._backfill(global_apps, None)

    open_keys = set(
        WorkspaceQuotaReservation.objects.filter(
            workspace=workspace, resource=QUOTA_RESOURCE_CONCURRENT_RANGES, released_at__isnull=True
        ).values_list("correlation_key", flat=True)
    )
    assert open_keys == {str(ready.request_id), str(provisioning.request_id), str(destroying.request_id)}


def test_backfill_is_idempotent():
    workspace = _workspace()
    _range(workspace, "ready")

    _BACKFILL._backfill(global_apps, None)
    _BACKFILL._backfill(global_apps, None)

    assert WorkspaceQuotaReservation.objects.filter(workspace=workspace).count() == 1


def test_backfill_fails_loudly_on_conflicting_workspace_evidence():
    workspace_a = _workspace("WS A")
    workspace_b = _workspace("WS B")
    shared_request = _range(workspace_a, "ready")
    # A second range projection reuses the same request UUID but a different
    # workspace binding: inconsistent evidence must fail loudly, not guess.
    RangeInstance.objects.create(
        request=shared_request,
        scenario_id="basic",
        user_id=User.objects.create_user(username="bf-dup@e.com", email="bf-dup@e.com").id,
        status="ready",
        workspace_id=workspace_b.pk,
    )

    with pytest.raises(RuntimeError, match="Inconsistent range workspace evidence"):
        _BACKFILL._backfill(global_apps, None)


def test_backfill_fails_loudly_on_singleton_range_request_mismatch():
    range_workspace = _workspace("Range WS")
    request_workspace = _workspace("Request WS")
    # A single range whose RangeInstance and Request bindings disagree is corrupt
    # evidence; the backfill must fail loudly rather than reserve against one side.
    _range(range_workspace, "ready", request_workspace_id=request_workspace.pk)

    with pytest.raises(RuntimeError, match=r"range .* vs request"):
        _BACKFILL._backfill(global_apps, None)
