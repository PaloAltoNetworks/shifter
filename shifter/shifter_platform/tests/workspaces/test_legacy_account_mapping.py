"""Legacy hierarchy mapping uses durable evidence and leaves rows untouched."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from workspaces.identity_mapping import plan_legacy_account_mapping
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db
User = get_user_model()


def _personal(name="legacy-owner"):
    user = User.objects.create_user(username=name)
    organization = Organization.objects.create(name="Personal")
    workspace = Workspace.objects.create(organization=organization, name="Personal", personal_for_user=user)
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="owner")
    OrganizationMembership.objects.create(organization=organization, user=user, role="admin")
    return user, organization, workspace


def test_clean_personal_hierarchy_maps_to_individual_without_rekeying_rows():
    user, organization, workspace = _personal()
    principal_id = uuid4()
    plan = plan_legacy_account_mapping(
        principal_by_user={user.id: principal_id},
        owner_ids_by_workspace={workspace.id: {user.id}},
        account_types_by_organization={},
    )

    assert not plan.blockers
    assert plan.individuals[0].principal_uuid == principal_id
    assert plan.individuals[0].legacy_organization_id == organization.id
    assert plan.individuals[0].legacy_workspace_id == workspace.id
    assert Organization.objects.get(pk=organization.id).account_id is None
    assert Workspace.objects.get(pk=workspace.id).uuid == workspace.uuid


def test_personal_structure_with_extra_member_or_owner_drift_blocks_mapping():
    user, organization, workspace = _personal()
    other = User.objects.create_user(username="other-member")
    WorkspaceMembership.objects.create(workspace=workspace, user=other, role="member")
    plan = plan_legacy_account_mapping(
        principal_by_user={user.id: uuid4(), other.id: uuid4()},
        owner_ids_by_workspace={workspace.id: {other.id}},
        account_types_by_organization={},
    )
    assert {blocker.reason for blocker in plan.blockers} == {"personal_membership_ambiguous", "resource_owner_mismatch"}
    assert not plan.individuals
    assert Organization.objects.get(pk=organization.id).account_id is None


def test_personal_mapping_requires_owner_evidence_for_the_workspace():
    user, _, _ = _personal()
    plan = plan_legacy_account_mapping(
        principal_by_user={user.id: uuid4()},
        owner_ids_by_workspace={},
        account_types_by_organization={},
    )
    assert not plan.individuals
    assert {blocker.reason for blocker in plan.blockers} == {"resource_owner_evidence_missing"}


def test_shared_organization_requires_explicit_type_keyed_by_public_uuid():
    organization = Organization.objects.create(name="A company")
    workspace = Workspace.objects.create(organization=organization, name="Project")
    missing = plan_legacy_account_mapping(
        principal_by_user={}, owner_ids_by_workspace={}, account_types_by_organization={}
    )
    assert missing.organizations == ()
    assert missing.blockers[0].reason == "account_type_missing"

    typed = plan_legacy_account_mapping(
        principal_by_user={},
        owner_ids_by_workspace={workspace.id: set()},
        account_types_by_organization={organization.uuid: "enterprise"},
    )
    assert typed.blockers == ()
    assert typed.organizations[0].organization_id == organization.id
    assert typed.organizations[0].account_kind == "enterprise"
    assert Workspace.objects.get(pk=workspace.id).organization_id == organization.id


def test_shared_organization_without_workspace_blocks_default_mapping():
    organization = Organization.objects.create(name="Empty team")
    plan = plan_legacy_account_mapping(
        principal_by_user={},
        owner_ids_by_workspace={},
        account_types_by_organization={organization.uuid: "team"},
    )
    assert not plan.organizations
    assert {blocker.reason for blocker in plan.blockers} == {"default_workspace_missing"}


def test_shared_mapping_requires_complete_owner_evidence():
    organization = Organization.objects.create(name="Team")
    workspace = Workspace.objects.create(organization=organization, name="Project")
    typed = {organization.uuid: "team"}
    missing = plan_legacy_account_mapping(
        principal_by_user={}, owner_ids_by_workspace={}, account_types_by_organization=typed
    )
    assert {blocker.reason for blocker in missing.blockers} == {"resource_owner_evidence_missing"}

    owner_without_principal = plan_legacy_account_mapping(
        principal_by_user={},
        owner_ids_by_workspace={workspace.id: {42}},
        account_types_by_organization=typed,
    )
    assert {blocker.reason for blocker in owner_without_principal.blockers} == {"principal_missing_for_resource_owner"}


def test_unrelated_blocker_with_same_integer_id_does_not_hide_valid_personal_mapping():
    Organization.objects.create(name="Unknown business")
    user, _, workspace = _personal("later-owner")
    plan = plan_legacy_account_mapping(
        principal_by_user={user.id: uuid4()},
        owner_ids_by_workspace={workspace.id: {user.id}},
        account_types_by_organization={},
    )
    assert len(plan.individuals) == 1
    assert plan.individuals[0].legacy_workspace_id == workspace.id
    assert {blocker.reason for blocker in plan.blockers} == {"account_type_missing"}


def test_shared_memberships_map_to_one_principal_at_each_existing_scope():
    user = User.objects.create_user(username="shared-member")
    principal_id = uuid4()
    organization = Organization.objects.create(name="Team")
    workspace = Workspace.objects.create(organization=organization, name="Project")
    OrganizationMembership.objects.create(organization=organization, user=user, role="admin")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="owner")

    plan = plan_legacy_account_mapping(
        principal_by_user={user.id: principal_id},
        owner_ids_by_workspace={workspace.id: {user.id}},
        account_types_by_organization={organization.uuid: "team"},
    )

    assert plan.blockers == ()
    assert {
        (member.scope_kind, member.scope_id, member.principal_uuid, member.role) for member in plan.memberships
    } == {
        ("organization", organization.id, principal_id, "admin"),
        ("workspace", workspace.id, principal_id, "owner"),
    }


def test_two_legacy_users_cannot_collapse_onto_one_principal():
    first, _, first_workspace = _personal("first-owner")
    second, _, second_workspace = _personal("second-owner")
    same_principal = uuid4()
    plan = plan_legacy_account_mapping(
        principal_by_user={first.id: same_principal, second.id: same_principal},
        owner_ids_by_workspace={first_workspace.id: {first.id}, second_workspace.id: {second.id}},
        account_types_by_organization={},
    )
    assert not plan.individuals
    assert {blocker.reason for blocker in plan.blockers} == {"duplicate_principal_mapping"}


def test_prepared_membership_fact_is_not_remapped_as_a_legacy_user():
    organization = Organization.objects.create(name="Mixed preparation")
    workspace = Workspace.objects.create(organization=organization, name="Shared")
    prepared = uuid4()
    WorkspaceMembership.objects.create(workspace=workspace, user=None, principal_uuid=prepared, role="")
    plan = plan_legacy_account_mapping(
        principal_by_user={},
        owner_ids_by_workspace={workspace.pk: set()},
        account_types_by_organization={organization.uuid: "team"},
    )
    assert not plan.blockers
    assert not plan.memberships
    assert WorkspaceMembership.objects.get(workspace=workspace).principal_uuid == prepared
