"""Unit tests for the #1325 backfill forward functions (ADR-046-R4).

These drive each migration's forward function directly against the *current*
models -- the same ``importlib`` pattern as
``tests.management.test_revoke_organizers_migration``. They cover the behavior
that does not depend on a row being unbound: per-user personal workspace
creation, idempotency, refusal to guess a tenant when historical ownership
evidence diverges, and refusal to rewrite a scope that already exists.

The binding behavior itself -- taking a genuinely unbound pre-#1325 row and
scoping it -- cannot be expressed against the current models, because
``cms.0040`` / ``engine.0042`` make the scope columns non-null. That half is
covered against the real historical schema in
``test_backfill_migration_schema``.
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model

from cms.models import RangeInstance, Request
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

User = get_user_model()

_PERSONAL = importlib.import_module("workspaces.migrations.0002_backfill_personal_workspaces")
_CMS_BINDING = importlib.import_module("cms.migrations.0039_backfill_workspace_bindings")

# Opaque scope for rows this module seeds as already-bound. The point of these
# tests is what happens around a binding, never the value itself.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db


def _user(suffix):
    return User.objects.create_user(username=f"mig-{suffix}@e.com", email=f"mig-{suffix}@e.com")


def _bound_cms_range_for(owner, workspace_id=_WORKSPACE_ID):
    """Seed a CMS request + range projection owned by ``owner``, already scoped."""
    cms_request = Request.objects.create(
        request_id=uuid.uuid4(),
        request_type="range",
        user=owner,
        workspace_id=workspace_id,
    )
    instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="basic",
        user_id=owner.id,
        status="ready",
        workspace_id=workspace_id,
    )
    return cms_request, instance


# ---------------------------------------------------------------------------
# Personal workspace backfill
# ---------------------------------------------------------------------------


def test_clean_install_with_no_users_creates_nothing():
    _PERSONAL.backfill_personal_workspaces(global_apps, None)

    assert Organization.objects.count() == 0
    assert Workspace.objects.count() == 0


def test_every_existing_user_gets_a_personal_workspace_and_owner_membership():
    first = _user("one")
    second = _user("two")

    _PERSONAL.backfill_personal_workspaces(global_apps, None)

    for owner in (first, second):
        workspace = Workspace.objects.get(personal_for_user=owner)
        assert workspace.organization is not None
        assert WorkspaceMembership.objects.filter(
            workspace=workspace, user=owner, role=WorkspaceRole.OWNER.value
        ).exists()


def test_no_shared_default_organization_is_created():
    """ADR-046-R4: the compatibility default is per user, never deployment-global."""
    first = _user("one")
    second = _user("two")

    _PERSONAL.backfill_personal_workspaces(global_apps, None)

    assert Organization.objects.count() == 2
    assert (
        Workspace.objects.get(personal_for_user=first).organization_id
        != Workspace.objects.get(personal_for_user=second).organization_id
    )


def test_backfill_is_idempotent():
    owner = _user("one")

    _PERSONAL.backfill_personal_workspaces(global_apps, None)
    _PERSONAL.backfill_personal_workspaces(global_apps, None)

    assert Workspace.objects.filter(personal_for_user=owner).count() == 1
    assert Organization.objects.count() == 1
    assert WorkspaceMembership.objects.filter(user=owner).count() == 1


def test_a_user_who_already_has_a_personal_workspace_keeps_it():
    owner = _user("one")
    organization = Organization.objects.create(name="Pre-existing")
    existing = Workspace.objects.create(organization=organization, name="Mine", personal_for_user=owner)

    _PERSONAL.backfill_personal_workspaces(global_apps, None)

    assert Workspace.objects.get(personal_for_user=owner).pk == existing.pk


# ---------------------------------------------------------------------------
# Divergent-evidence guards (these scan every row, bound or not)
# ---------------------------------------------------------------------------


def test_divergent_projection_ownership_stops_the_migration():
    """A range projection whose owner disagrees with its request is not guessed at."""
    owner = _user("one")
    other = _user("two")
    _cms_request, instance = _bound_cms_range_for(owner)
    RangeInstance.objects.filter(pk=instance.pk).update(user_id=other.id)

    _PERSONAL.backfill_personal_workspaces(global_apps, None)
    with pytest.raises(RuntimeError) as failure:
        _CMS_BINDING.backfill_workspace_bindings(global_apps, None)

    # The diagnostic identifies the row, never the user's email or credentials.
    message = str(failure.value)
    assert str(instance.pk) in message
    assert "@e.com" not in message


def test_divergent_cross_layer_ownership_stops_the_migration():
    """CMS and Engine disagreeing about a range's owner is a deployment blocker."""
    from engine.models import Range as EngineRange
    from engine.models import Request as EngineRequest

    owner = _user("one")
    other = _user("two")
    cms_request, _instance = _bound_cms_range_for(owner)
    engine_request = EngineRequest.objects.create(request_id=cms_request.request_id, request_type="range", user=other)
    EngineRange.objects.create(user=other, request=engine_request, status="ready", workspace_id=_WORKSPACE_ID)

    _PERSONAL.backfill_personal_workspaces(global_apps, None)
    with pytest.raises(RuntimeError):
        _CMS_BINDING.backfill_workspace_bindings(global_apps, None)


def test_an_already_bound_row_is_not_rebound():
    """The backfill fills gaps; it never rewrites an existing scope."""
    owner = _user("one")
    organization = Organization.objects.create(name="Chosen")
    chosen = Workspace.objects.create(organization=organization, name="Chosen")
    _cms_request, instance = _bound_cms_range_for(owner, workspace_id=chosen.pk)

    _PERSONAL.backfill_personal_workspaces(global_apps, None)
    _CMS_BINDING.backfill_workspace_bindings(global_apps, None)

    assert RangeInstance.objects.get(pk=instance.pk).workspace_id == chosen.pk
