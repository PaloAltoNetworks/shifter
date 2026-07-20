"""Tests for engine migration 0022 legacy ARN backfill."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model

from engine.models import Range

pytestmark = pytest.mark.django_db

User = get_user_model()
LEGACY_ARN = "arn:aws:ecs:us-east-2:123:task/legacy-provision"
_backfill_module = importlib.import_module("engine.migrations.0022_range_provisioning_teardown_task_arns")
_backfill_task_arns = _backfill_module._backfill_task_arns


@pytest.fixture
def user(db):
    return User.objects.create_user(username="mig-0022@example.com", email="mig-0022@example.com")


def test_backfill_copies_legacy_arn_to_provisioning_for_ready_range(user):
    row = Range.objects.create(
        user=user,
        status=Range.Status.READY,
        step_function_execution_arn=LEGACY_ARN,
    )
    Range.objects.filter(id=row.id).update(provisioning_task_arn="", teardown_task_arn="")

    _backfill_task_arns(apps, None)

    row.refresh_from_db()
    assert row.provisioning_task_arn == LEGACY_ARN
    assert row.teardown_task_arn == ""


def test_backfill_copies_legacy_arn_to_teardown_for_destroying_range(user):
    row = Range.objects.create(
        user=user,
        status=Range.Status.DESTROYING,
        step_function_execution_arn=LEGACY_ARN,
    )
    Range.objects.filter(id=row.id).update(provisioning_task_arn="", teardown_task_arn="")

    _backfill_task_arns(apps, None)

    row.refresh_from_db()
    assert row.teardown_task_arn == LEGACY_ARN
    assert row.provisioning_task_arn == ""
