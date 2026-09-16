"""Unit tests for the #1939 organization-admin backfill (ADR-048).

Drives the migration's forward function directly against the current models --
the same ``importlib`` pattern as ``test_backfill_migration`` -- covering the
behavior that matters: one bootstrap admin per personal organization, idempotency
on re-run, and a clean install seeding nothing.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model

from workspaces.models import Organization, OrganizationMembership, Workspace
from workspaces.roles import OrganizationRole

User = get_user_model()

_BACKFILL = importlib.import_module("workspaces.migrations.0005_backfill_organization_admins")

pytestmark = pytest.mark.django_db


def _user(suffix):
    return User.objects.create_user(username=f"orgmig-{suffix}@e.com", email=f"orgmig-{suffix}@e.com")


def _personal_org_for(user):
    organization = Organization.objects.create(name="Personal")
    Workspace.objects.create(organization=organization, name="Personal", personal_for_user=user)
    return organization


def test_clean_install_with_no_personal_workspaces_seeds_nothing():
    _BACKFILL.backfill_organization_admins(global_apps, None)

    assert OrganizationMembership.objects.count() == 0


def test_every_personal_organization_gets_its_owner_as_admin():
    first = _user("one")
    second = _user("two")
    first_org = _personal_org_for(first)
    second_org = _personal_org_for(second)

    _BACKFILL.backfill_organization_admins(global_apps, None)

    assert OrganizationMembership.objects.filter(
        organization=first_org, user=first, role=OrganizationRole.ADMIN.value
    ).exists()
    assert OrganizationMembership.objects.filter(
        organization=second_org, user=second, role=OrganizationRole.ADMIN.value
    ).exists()


def test_backfill_is_idempotent():
    user = _user("solo")
    _personal_org_for(user)

    _BACKFILL.backfill_organization_admins(global_apps, None)
    _BACKFILL.backfill_organization_admins(global_apps, None)

    assert OrganizationMembership.objects.filter(user=user).count() == 1


def test_backfill_skips_non_personal_organizations():
    organization = Organization.objects.create(name="Shared")
    Workspace.objects.create(organization=organization, name="Shared", personal_for_user=None)

    _BACKFILL.backfill_organization_admins(global_apps, None)

    assert not OrganizationMembership.objects.filter(organization=organization).exists()
