"""Effective range egress resolution at the CMS launch seam (PLAT-238, ADR-017-R5).

The launch-admission seam turns a workspace's stored egress selector into the one
closed :class:`~installation.range_egress.RangeEgressMode` value pinned on the
Engine range. These tests drive that resolution against real workspace rows so a
regression that dropped the override, defaulted a missing workspace to a
permissive posture, or mis-mapped the selector goes red.
"""

from __future__ import annotations

import pytest

from cms.services._range_workspace import (
    resolve_effective_egress_mode,
    resolve_effective_egress_mode_locked,
)
from workspaces.models import Organization, Workspace

pytestmark = pytest.mark.django_db


def _workspace(egress_policy: str) -> Workspace:
    organization = Organization.objects.create(name="Egress Org")
    return Workspace.objects.create(organization=organization, name="ws", egress_policy=egress_policy)


def test_workspace_none_resolves_to_zero_egress():
    workspace = _workspace("none")

    assert resolve_effective_egress_mode(workspace.pk) == "none"
    assert resolve_effective_egress_mode_locked(workspace.pk) == "none"


def test_workspace_status_quo_inherits_the_baseline():
    workspace = _workspace("status-quo")

    assert resolve_effective_egress_mode(workspace.pk) == "status-quo"


def test_missing_workspace_fails_closed_rather_than_defaulting():
    from workspaces.services import WorkspaceLifecycleError

    with pytest.raises(WorkspaceLifecycleError):
        resolve_effective_egress_mode(999_999)
