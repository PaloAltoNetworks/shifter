"""Account hierarchy, default creation, and scope ancestry (ADR-066)."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from management.services import create_service_principal, set_service_contact
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.models import AuditLog
from workspaces.models import Account, AccountMembership, Organization, Workspace, WorkspaceMembership
from workspaces.services import (
    AccountScopeError,
    WorkspaceAuditContext,
    WorkspaceLifecycleError,
    add_account_member,
    archive_workspace,
    create_account,
    create_account_organization,
    create_account_workspace,
    ensure_default_hierarchy,
    resolve_resource_scope,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_account_credential_target_rejects_invalid_individual_subdivisions():
    from workspaces.services import hierarchy_target_scope

    account = create_account(kind="individual", name="Person", owner=PrincipalRef(uuid4(), "human"))
    assert hierarchy_target_scope("account", account.uuid) == ResourceScope("account", account.uuid)
    Organization.objects.create(account_id=account.id, name="Invalid subdivision")
    with pytest.raises(AccountScopeError):
        hierarchy_target_scope("account", account.uuid)


def test_individual_account_has_direct_owner_and_no_subdivisions_or_implicit_grant():
    owner = PrincipalRef(uuid=uuid4(), kind="human")
    account = create_account(kind="individual", name="A person", owner=owner)

    assert account.kind == "individual"
    assert account.individual_principal_uuid == owner.uuid
    assert not Organization.objects.filter(account_id=account.id).exists()
    assert not AccountMembership.objects.filter(account_id=account.id).exists()
    assert resolve_resource_scope(ResourceScope(kind="account", account_uuid=account.uuid)).account_id == account.id
    ensure_default_hierarchy(account.uuid)
    assert not Organization.objects.filter(account_id=account.id).exists()


@pytest.mark.parametrize("kind", ["team", "enterprise"])
def test_business_account_defaults_are_idempotent_and_do_not_grant_roles(kind):
    account = create_account(kind=kind, name="A group")
    ensure_default_hierarchy(account.uuid)
    organizations = list(Organization.objects.filter(account_id=account.id))
    assert len(organizations) == 1
    assert organizations[0].is_default is True
    workspaces = list(Workspace.objects.filter(organization=organizations[0]))
    assert len(workspaces) == 1
    assert workspaces[0].is_default is True
    assert not organizations[0].memberships.exists()
    assert not workspaces[0].memberships.exists()
    assert not AccountMembership.objects.filter(account_id=account.id).exists()


def test_additional_organization_gets_its_own_default_workspace_and_extra_workspaces():
    account = create_account(kind="team", name="A group")
    organization = create_account_organization(account.uuid, "Second")
    extra = create_account_workspace(account.uuid, organization.uuid, "Extra")

    assert organization.account_id == account.id
    assert organization.is_default is False
    assert Workspace.objects.filter(organization_id=organization.id, is_default=True).count() == 1
    assert extra.organization_id == organization.id
    assert extra.is_default is False


def test_one_human_can_join_multiple_accounts_without_new_identity_or_automatic_policy():
    principal = PrincipalRef(uuid=uuid4(), kind="human")
    first = create_account(kind="individual", name="Personal", owner=principal)
    second = create_account(kind="team", name="Work")
    add_account_member(first.uuid, principal)
    add_account_member(second.uuid, principal)

    assert set(
        AccountMembership.objects.filter(principal_uuid=principal.uuid).values_list("account_id", flat=True)
    ) == {
        first.id,
        second.id,
    }


def test_service_account_membership_survives_contact_removal_without_rekeying():
    creator = User.objects.create_user(username="service-creator")
    service = create_service_principal("Automation", created_by=creator, responsible_user=creator)
    account = create_account(kind="enterprise", name="Customer")
    add_account_member(account.uuid, service)

    set_service_contact(service, None)
    from management.services import mark_user_deleted

    mark_user_deleted(creator)
    assert creator.identity_principal.user_id == creator.pk

    assert AccountMembership.objects.filter(account_id=account.id, principal_uuid=service.uuid).count() == 1
    assert resolve_resource_scope(ResourceScope(kind="account", account_uuid=account.uuid)).account_id == account.id


def test_cross_account_or_missing_ancestry_fails_closed():
    first = create_account(kind="team", name="First")
    other = create_account(kind="enterprise", name="Other")
    organization = Organization.objects.get(account_id=other.id, is_default=True)
    workspace = Workspace.objects.get(organization=organization, is_default=True)

    for scope in (
        ResourceScope(kind="account", account_uuid=first.uuid, organization_uuid=organization.uuid),
        ResourceScope(
            kind="account",
            account_uuid=first.uuid,
            organization_uuid=organization.uuid,
            workspace_uuid=workspace.uuid,
        ),
        ResourceScope(kind="account", account_uuid=uuid4()),
    ):
        with pytest.raises(AccountScopeError, match="Scope unavailable"):
            resolve_resource_scope(scope)


def test_individual_rejects_organization_even_if_a_corrupt_row_is_attached():
    principal = PrincipalRef(uuid=uuid4(), kind="human")
    individual = create_account(kind="individual", name="A person", owner=principal)
    with pytest.raises(AccountScopeError):
        create_account_organization(individual.uuid, "Invalid")
    Organization.objects.create(account_id=individual.id, name="Corrupt")
    with pytest.raises(AccountScopeError):
        resolve_resource_scope(ResourceScope(kind="account", account_uuid=individual.uuid))


def test_database_rejects_multiple_defaults_and_invalid_account_type():
    account = create_account(kind="team", name="A group")
    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(account_id=account.id, name="Another default", is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(kind="invalid", name="Bad")


def test_business_default_workspace_cannot_be_archived_without_reassignment():
    actor = User.objects.create_user(username="default-owner")
    account = create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    WorkspaceMembership.objects.create(workspace=workspace, user=actor, role="owner")

    with pytest.raises(WorkspaceLifecycleError) as error:
        archive_workspace(
            actor,
            workspace.uuid,
            audit=WorkspaceAuditContext(actor_type="user", actor_id=actor.pk),
        )
    assert error.value.code == "default_workspace"
    workspace.refresh_from_db()
    assert workspace.archived_at is None


def test_account_and_membership_mutations_have_bounded_audit_evidence():
    principal = PrincipalRef(uuid=uuid4(), kind="human")
    account = create_account(kind="team", name="A private customer")
    add_account_member(account.uuid, principal)
    account_event = AuditLog.objects.get(entity_type="account", entity_id=account.id)
    membership_event = AuditLog.objects.get(entity_type="account_membership")
    assert "A private customer" not in str(account_event.new_state)
    assert str(principal.uuid) not in str(membership_event.new_state)
