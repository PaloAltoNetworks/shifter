"""Workspace scope binding on the range create/reassign paths (ADR-046-R3, #1325).

The binding is written once by the trusted CMS launch path and persisted on all
three ownership projections -- CMS request intent, the CMS range projection, and
the Engine range -- so a later scoping change (#1327) has a consistent fact to
read. These tests drive the real service; they go red if the binding stops being
written, if the projections disagree, or if reassignment stops checking the
target user's membership.
"""

import pytest

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from engine.models import Range as EngineRange
from workspaces import services as workspace_services

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    """Range owner for the launch paths under test."""
    return django_user_model.objects.create_user(username="ws-owner@e.com", email="ws-owner@e.com")


def _launch(user, make_agent, hydratable_scenario):
    """Launch a range through the real CMS facade and return its projections."""
    agent = make_agent(user)
    services.create_range(user, hydratable_scenario.scenario_id, {"windows": agent.id})
    range_instance = RangeInstance.objects.get(user_id=user.id)
    cms_request = range_instance.request
    engine_range = EngineRange.objects.get(request__request_id=cms_request.request_id)
    return cms_request, range_instance, engine_range


def test_launching_a_range_binds_it_to_the_owner_personal_workspace(user, make_agent, hydratable_scenario):
    cms_request, range_instance, engine_range = _launch(user, make_agent, hydratable_scenario)

    personal = workspace_services.resolve_personal_workspace(user)
    assert cms_request.workspace_id == personal.workspace_id
    assert range_instance.workspace_id == personal.workspace_id
    assert engine_range.workspace_id == personal.workspace_id


def test_all_three_ownership_projections_agree(user, make_agent, hydratable_scenario):
    """A range scoped in one projection but not another is the drift ADR-046-R3 forbids."""
    cms_request, range_instance, engine_range = _launch(user, make_agent, hydratable_scenario)

    bindings = {cms_request.workspace_id, range_instance.workspace_id, engine_range.workspace_id}
    assert len(bindings) == 1
    assert bindings.pop() is not None


def test_two_users_ranges_land_in_different_workspaces(user, django_user_model, make_agent, hydratable_scenario):
    other = django_user_model.objects.create_user(username="ws-other@e.com", email="ws-other@e.com")
    _, first_instance, _ = _launch(user, make_agent, hydratable_scenario)
    _, second_instance, _ = _launch(other, make_agent, hydratable_scenario)

    assert first_instance.workspace_id != second_instance.workspace_id


def test_launching_does_not_change_user_ownership(user, make_agent, hydratable_scenario):
    """Workspace scope is additive: the range's user owner is unchanged."""
    cms_request, range_instance, engine_range = _launch(user, make_agent, hydratable_scenario)

    assert cms_request.user_id == user.id
    assert range_instance.user_id == user.id
    assert engine_range.user_id == user.id


def test_reassignment_to_a_user_outside_the_workspace_is_refused(
    user, django_user_model, make_agent, hydratable_scenario
):
    """A range must not silently keep a scope its new owner cannot reach."""
    _, range_instance, _ = _launch(user, make_agent, hydratable_scenario)
    outsider = django_user_model.objects.create_user(username="ws-out@e.com", email="ws-out@e.com")
    workspace_services.resolve_personal_workspace(outsider)

    with pytest.raises(CMSError):
        services.reassign_range_owner(range_instance.pk, outsider)

    range_instance.refresh_from_db()
    assert range_instance.user_id == user.id


def test_reassignment_within_the_workspace_is_allowed(user, django_user_model, make_agent, hydratable_scenario):
    """A member of the range's workspace may take ownership."""
    from workspaces.models import Workspace, WorkspaceMembership
    from workspaces.roles import WorkspaceRole

    _, range_instance, engine_range = _launch(user, make_agent, hydratable_scenario)
    teammate = django_user_model.objects.create_user(username="ws-team@e.com", email="ws-team@e.com")
    workspace = Workspace.objects.get(pk=range_instance.workspace_id)
    WorkspaceMembership.objects.create(workspace=workspace, user=teammate, role=WorkspaceRole.OWNER.value)

    services.reassign_range_owner(range_instance.pk, teammate)

    engine_range.refresh_from_db()
    assert engine_range.user_id == teammate.id
    # Scope is unchanged by an in-workspace reassignment.
    assert engine_range.workspace_id == workspace.pk


def test_rehoming_moves_the_scope_to_the_new_owner_on_every_projection(
    user, django_user_model, make_agent, hydratable_scenario
):
    """An explicit rehome carries the range's scope across all three projections.

    This is the handover ADR-046-R3 sanctions -- a CTF spare range given to a
    participant in another tenant. It must leave nothing pointing at the previous
    workspace, or a later scoped query would still see the old tenant's range.
    """
    cms_request, range_instance, engine_range = _launch(user, make_agent, hydratable_scenario)
    original = range_instance.workspace_id
    newcomer = django_user_model.objects.create_user(username="ws-new@e.com", email="ws-new@e.com")
    expected = workspace_services.resolve_personal_workspace(newcomer).workspace_id

    services.reassign_range_owner(range_instance.pk, newcomer, rehome=True)

    range_instance.refresh_from_db()
    cms_request.refresh_from_db()
    engine_range.refresh_from_db()
    assert expected != original
    assert range_instance.workspace_id == expected
    assert cms_request.workspace_id == expected
    assert engine_range.workspace_id == expected
    assert engine_range.user_id == newcomer.id


def test_rehoming_is_never_implicit(user, django_user_model, make_agent, hydratable_scenario):
    """The same handover without rehome=True is refused, not silently rescoped."""
    _, range_instance, _ = _launch(user, make_agent, hydratable_scenario)
    original = range_instance.workspace_id
    newcomer = django_user_model.objects.create_user(username="ws-implicit@e.com", email="ws-implicit@e.com")
    workspace_services.resolve_personal_workspace(newcomer)

    with pytest.raises(CMSError):
        services.reassign_range_owner(range_instance.pk, newcomer)

    range_instance.refresh_from_db()
    assert range_instance.workspace_id == original
    assert range_instance.user_id == user.id


# An unbound range is no longer a reachable state: cms.0040 / engine.0042 make
# all three scope columns non-null, so the "legacy NULL binding" case this file
# used to cover cannot be constructed here. The service-level guard that refuses
# a null binding is still exercised directly in
# tests/workspaces/test_services.py::test_bound_workspace_authorization_denies_a_null_binding,
# and the pre-migration shape is covered against the real historical schema in
# tests/workspaces/test_backfill_migration_schema.py.


def test_the_active_range_constraint_is_unchanged(user, make_agent, hydratable_scenario):
    """Adding workspace scope must not widen or narrow the per-user active-range rule."""
    _launch(user, make_agent, hydratable_scenario)
    agent = make_agent(user)

    with pytest.raises(CMSError):
        services.create_range(user, hydratable_scenario.scenario_id, {"windows": agent.id})

    assert RangeInstance.objects.filter(user_id=user.id, deleted_at__isnull=True).count() == 1
