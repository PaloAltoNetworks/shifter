"""End-to-end migration test for the #1325 tenancy backfill (ADR-046-R4).

Unlike ``test_backfill_migration``, which drives the forward functions against
the *current* models, this module runs the real migration graph against the real
historical schema: it migrates the database back to the point where the scope
columns were still nullable, seeds genuinely unbound rows the way a pre-#1325
deployment has them, then migrates forward and asserts the outcome.

That distinction is load-bearing. Once ``cms.0040`` / ``engine.0042`` make the
columns non-null, the current models can no longer express an unbound row, so a
test written against them cannot prove the backfill binds anything. The upgrade
path this migration exists for is only reachable through the historical schema.

The suite is transactional and restores the database to the latest migration
state on teardown so it cannot leave a half-migrated schema behind for other
modules sharing the worker.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# State just before the scope columns exist / are populated.
BEFORE = [
    ("workspaces", "0001_initial"),
    ("cms", "0038_rangeinstance_workspace_id_request_workspace_id"),
    ("engine", "0040_range_workspace_id"),
]
# State after the backfill and the non-null tightening.
AFTER = [
    ("workspaces", "0002_backfill_personal_workspaces"),
    ("cms", "0040_workspace_binding_required"),
    ("engine", "0042_workspace_binding_required"),
]

pytestmark = [pytest.mark.django_db(transaction=True)]


def _migrate(targets):
    """Migrate to ``targets`` and return the resulting historical app registry."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


@pytest.fixture
def historical():
    """Rewind to the pre-backfill schema, yield its models, restore afterwards."""
    apps = _migrate(BEFORE)
    try:
        yield apps
    finally:
        # Always land back on the full graph, whatever the test did.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _seed_user(apps, suffix):
    user_model = apps.get_model("auth", "User")
    return user_model.objects.create(username=f"hist-{suffix}", email=f"hist-{suffix}@e.com")


def _seed_unbound_range(apps, owner):
    """Seed the pre-#1325 shape: a CMS request/projection and engine range with NULL scope."""
    request_model = apps.get_model("cms", "Request")
    instance_model = apps.get_model("cms", "RangeInstance")
    engine_request_model = apps.get_model("engine", "Request")
    engine_range_model = apps.get_model("engine", "Range")

    request_id = uuid.uuid4()
    cms_request = request_model.objects.create(request_id=request_id, request_type="range", user_id=owner.pk)
    instance = instance_model.objects.create(request=cms_request, scenario_id="basic", user_id=owner.pk, status="ready")
    engine_request = engine_request_model.objects.create(request_id=request_id, request_type="range", user_id=owner.pk)
    engine_range = engine_range_model.objects.create(user_id=owner.pk, request=engine_request, status="ready")
    return cms_request, instance, engine_range


def test_pre_migration_rows_really_are_unbound(historical):
    """Guard the premise: the historical schema must allow a NULL scope."""
    owner = _seed_user(historical, "premise")
    cms_request, instance, engine_range = _seed_unbound_range(historical, owner)

    assert cms_request.workspace_id is None
    assert instance.workspace_id is None
    assert engine_range.workspace_id is None


def test_upgrade_binds_every_existing_range_to_its_owner_personal_workspace(historical):
    owner = _seed_user(historical, "owner")
    cms_request, instance, engine_range = _seed_unbound_range(historical, owner)

    apps = _migrate(AFTER)

    workspace_model = apps.get_model("workspaces", "Workspace")
    membership_model = apps.get_model("workspaces", "WorkspaceMembership")
    workspace = workspace_model.objects.get(personal_for_user_id=owner.pk)
    assert membership_model.objects.filter(workspace_id=workspace.pk, user_id=owner.pk, role="owner").exists()

    expected = workspace.pk
    assert apps.get_model("cms", "Request").objects.get(pk=cms_request.pk).workspace_id == expected
    assert apps.get_model("cms", "RangeInstance").objects.get(pk=instance.pk).workspace_id == expected
    assert apps.get_model("engine", "Range").objects.get(pk=engine_range.pk).workspace_id == expected


def test_two_owners_ranges_land_in_different_workspaces_after_upgrade(historical):
    first = _seed_user(historical, "first")
    second = _seed_user(historical, "second")
    _, first_instance, _ = _seed_unbound_range(historical, first)
    _, second_instance, _ = _seed_unbound_range(historical, second)

    apps = _migrate(AFTER)

    instance_model = apps.get_model("cms", "RangeInstance")
    first_scope = instance_model.objects.get(pk=first_instance.pk).workspace_id
    second_scope = instance_model.objects.get(pk=second_instance.pk).workspace_id
    assert first_scope != second_scope
    # ADR-046-R4: per-user personal organizations, never one shared default.
    assert apps.get_model("workspaces", "Organization").objects.count() == 2


def test_upgrade_leaves_no_unbound_rows_behind(historical):
    """After the upgrade the invariant is total, not partial."""
    for suffix in ("a", "b", "c"):
        _seed_unbound_range(historical, _seed_user(historical, suffix))

    apps = _migrate(AFTER)

    for app_label, model_name in (("cms", "Request"), ("cms", "RangeInstance"), ("engine", "Range")):
        model = apps.get_model(app_label, model_name)
        assert not model.objects.filter(workspace_id__isnull=True).exists()


def test_a_user_with_no_ranges_still_gets_a_personal_workspace(historical):
    owner = _seed_user(historical, "idle")

    apps = _migrate(AFTER)

    assert apps.get_model("workspaces", "Workspace").objects.filter(personal_for_user_id=owner.pk).exists()


def test_clean_install_upgrade_creates_no_tenancy_rows(historical):
    """An empty deployment migrates without inventing an organization."""
    apps = _migrate(AFTER)

    assert apps.get_model("workspaces", "Organization").objects.count() == 0
    assert apps.get_model("workspaces", "Workspace").objects.count() == 0
