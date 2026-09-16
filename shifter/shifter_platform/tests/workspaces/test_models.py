"""Invariant tests for the workspaces tenancy models (ADR-046, issue #1325).

Drives the real ``Organization`` / ``Workspace`` / ``WorkspaceMembership`` rows
against the database so the invariants that matter -- one organization per
workspace, one membership per (workspace, user), one personal workspace per
user, immutable public UUIDs -- fail here if a constraint is dropped rather than
being asserted only in prose.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.roles import OrganizationRole, WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix="a"):
    return User.objects.create_user(username=f"ws-{suffix}@e.com", email=f"ws-{suffix}@e.com")


def _organization(name="Research Lab"):
    return Organization.objects.create(name=name)


def _workspace(organization=None, name="Team", personal_for_user=None):
    return Workspace.objects.create(
        organization=organization or _organization(),
        name=name,
        personal_for_user=personal_for_user,
    )


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


def test_organization_gets_a_stable_public_uuid_distinct_from_its_internal_id():
    organization = _organization()

    assert isinstance(organization.uuid, uuid.UUID)
    assert organization.pk != organization.uuid
    reloaded = Organization.objects.get(pk=organization.pk)
    assert reloaded.uuid == organization.uuid


def test_organization_public_uuid_is_unique():
    first = _organization("First")
    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(name="Second", uuid=first.uuid)


def test_organization_profile_fields_default_to_empty_unset_values():
    organization = _organization()

    # ``description``/``support_email``/``support_url`` are optional profile
    # fields (PLAT-232); empty string is the canonical "unset" value, not NULL.
    reloaded = Organization.objects.get(pk=organization.pk)
    assert reloaded.description == ""
    assert reloaded.support_email == ""
    assert reloaded.support_url == ""


def test_organization_profile_fields_round_trip():
    organization = Organization.objects.create(
        name="Research Lab",
        description="A tenancy grouping for the research team.",
        support_email="help@example.com",
        support_url="https://example.com/support",
    )

    reloaded = Organization.objects.get(pk=organization.pk)
    assert reloaded.description == "A tenancy grouping for the research team."
    assert reloaded.support_email == "help@example.com"
    assert reloaded.support_url == "https://example.com/support"


# ---------------------------------------------------------------------------
# OrganizationMembership (ADR-048: organization administrator authority)
# ---------------------------------------------------------------------------


def test_organization_membership_is_unique_per_organization_and_user():
    organization = _organization()
    user = _user()
    OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationRole.ADMIN)

    with pytest.raises(IntegrityError), transaction.atomic():
        OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationRole.ADMIN)


def test_organization_membership_role_is_a_closed_vocabulary():
    membership = OrganizationMembership(organization=_organization(), user=_user(), role="superuser")

    with pytest.raises(ValidationError, match="role"):
        membership.full_clean()


def test_organization_membership_role_is_enforced_by_the_database():
    organization = _organization()
    user = _user()

    with pytest.raises(IntegrityError), transaction.atomic():
        OrganizationMembership.objects.create(organization=organization, user=user, role="superuser")


def test_a_user_may_administer_several_organizations():
    user = _user()
    first = _organization("First")
    second = _organization("Second")
    OrganizationMembership.objects.create(organization=first, user=user, role=OrganizationRole.ADMIN)
    OrganizationMembership.objects.create(organization=second, user=user, role=OrganizationRole.ADMIN)

    assert OrganizationMembership.objects.filter(user=user).count() == 2


def test_deleting_an_organization_removes_its_admin_memberships():
    organization = _organization()
    user = _user()
    OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationRole.ADMIN)

    organization.delete()

    assert not OrganizationMembership.objects.filter(user=user).exists()


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def test_workspace_belongs_to_exactly_one_organization():
    organization = _organization()
    workspace = _workspace(organization=organization)

    assert workspace.organization_id == organization.pk
    assert list(organization.workspaces.all()) == [workspace]


def test_workspace_organization_is_required():
    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(organization=None, name="Orphan")


def test_workspace_name_is_unique_within_an_organization_but_not_across_them():
    organization = _organization()
    _workspace(organization=organization, name="Blue Team")
    # The same name under a different organization is allowed: names are scoped
    # to their tenancy boundary, never deployment-global.
    _workspace(organization=_organization("Other"), name="Blue Team")

    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(organization=organization, name="Blue Team")


def test_a_user_has_at_most_one_personal_workspace():
    user = _user()
    _workspace(name="Personal", personal_for_user=user)

    second_organization = _organization("Second personal")

    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(
            organization=second_organization,
            name="Personal again",
            personal_for_user=user,
        )


def test_many_workspaces_may_be_non_personal():
    organization = _organization()
    _workspace(organization=organization, name="One")
    _workspace(organization=organization, name="Two")

    assert Workspace.objects.filter(personal_for_user__isnull=True).count() == 2


# ---------------------------------------------------------------------------
# WorkspaceMembership
# ---------------------------------------------------------------------------


def test_membership_is_unique_per_workspace_and_user():
    workspace = _workspace()
    user = _user()
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceRole.OWNER)

    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceRole.OWNER)


def test_a_user_may_hold_memberships_in_several_workspaces():
    user = _user()
    first = _workspace(name="First")
    second = _workspace(name="Second")
    WorkspaceMembership.objects.create(workspace=first, user=user, role=WorkspaceRole.OWNER)
    WorkspaceMembership.objects.create(workspace=second, user=user, role=WorkspaceRole.OWNER)

    assert WorkspaceMembership.objects.filter(user=user).count() == 2


def test_membership_role_is_a_closed_vocabulary():
    workspace = _workspace()
    membership = WorkspaceMembership(workspace=workspace, user=_user(), role="superuser")

    with pytest.raises(ValidationError, match="role"):
        membership.full_clean()


def test_membership_role_is_enforced_by_the_database():
    workspace = _workspace()
    user = _user()

    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.create(workspace=workspace, user=user, role="superuser")


def test_deleting_a_workspace_removes_its_memberships():
    workspace = _workspace()
    user = _user()
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceRole.OWNER)

    workspace.delete()

    assert not WorkspaceMembership.objects.filter(user=user).exists()
