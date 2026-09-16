"""Tests for the dev/test-only ``seed_e2e`` management command."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from workspaces.management.commands.seed_e2e import (
    STAFF_EMAIL,
    STANDARD_EMAIL,
    THREAT_EMAIL,
)
from workspaces.models import OrganizationMembership
from workspaces.roles import OrganizationRole

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_seed_creates_synthetic_actors_and_org_authority():
    call_command("seed_e2e")

    staff = User.objects.get(username=STAFF_EMAIL)
    assert staff.is_staff is True
    assert staff.is_active is True
    # The staff actor administers an organization (workspace-console precondition).
    assert OrganizationMembership.objects.filter(user=staff, role=OrganizationRole.ADMIN.value).exists()

    threat = User.objects.get(username=THREAT_EMAIL)
    assert threat.groups.filter(name="Threat Research").exists()
    assert threat.is_staff is False

    standard = User.objects.get(username=STANDARD_EMAIL)
    assert standard.is_active is True
    assert standard.is_staff is False


def test_seed_is_idempotent():
    call_command("seed_e2e")
    call_command("seed_e2e")

    assert User.objects.filter(username=STAFF_EMAIL).count() == 1
    staff = User.objects.get(username=STAFF_EMAIL)
    # The admin membership is not duplicated on re-run.
    assert OrganizationMembership.objects.filter(user=staff, role=OrganizationRole.ADMIN.value).count() == 1
    assert Group.objects.filter(name="Threat Research").count() == 1


@override_settings(DEBUG=False, ENVIRONMENT="production")
def test_seed_refuses_production_posture():
    with pytest.raises(CommandError):
        call_command("seed_e2e")

    # Fail-closed: nothing is created when the gate refuses.
    assert not User.objects.filter(username=STAFF_EMAIL).exists()
    assert not User.objects.filter(username=THREAT_EMAIL).exists()
