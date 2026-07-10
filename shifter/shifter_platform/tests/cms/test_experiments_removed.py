"""Regression checks for the removed legacy experiments feature."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.urls import Resolver404, resolve

from shared.api_tokens import scopes

_migration_module = importlib.import_module("cms.migrations.0034_remove_legacy_experiments")
_remove_legacy_experiments = _migration_module.remove_legacy_experiments


def test_legacy_experiments_app_is_not_installed():
    assert "cms.experiments.apps.ExperimentsConfig" not in settings.INSTALLED_APPS


def test_legacy_experiments_runtime_contract_is_removed():
    assert not hasattr(settings, "EXPERIMENTS_ENABLED")
    assert "experiments" not in settings.QUEUE_CONFIG


def test_legacy_script_surfaces_are_not_routed():
    for path in (
        "/mission-control/files/",
        "/mission-control/api/scripts/",
        "/api/v1/mission-control/scripts/",
        "/api/v1/mission-control/scripts/upload/",
    ):
        try:
            resolve(path)
        except Resolver404:
            continue
        raise AssertionError(f"legacy experiment script path still resolves: {path}")


def test_legacy_script_token_scopes_are_removed():
    assert "mission_control:script:read" not in scopes.KNOWN_SCOPES
    assert "mission_control:script:write" not in scopes.KNOWN_SCOPES


@pytest.mark.django_db
def test_legacy_experiments_cleanup_removes_auth_content_type_dependencies():
    content_type = ContentType.objects.create(app_label="experiments", model="experiment")
    permission = Permission.objects.create(
        content_type=content_type,
        codename="delete_experiment",
        name="Can delete legacy experiment",
    )
    group = Group.objects.create(name="legacy-experiment-operators")
    group.permissions.add(permission)
    user = get_user_model().objects.create_user(username="legacy-experiments@example.com")
    user.user_permissions.add(permission)
    MigrationRecorder(connection).record_applied("experiments", "0001_initial")

    schema_editor = SimpleNamespace(connection=connection, quote_name=connection.ops.quote_name)

    _remove_legacy_experiments(apps, schema_editor)

    assert not ContentType.objects.filter(app_label="experiments").exists()
    assert not Permission.objects.filter(id=permission.id).exists()
    assert not group.permissions.through.objects.filter(permission_id=permission.id).exists()
    assert not user.user_permissions.through.objects.filter(permission_id=permission.id).exists()
    assert not MigrationRecorder(connection).migration_qs.filter(app="experiments").exists()
