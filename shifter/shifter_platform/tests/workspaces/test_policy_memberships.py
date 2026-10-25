"""Principal membership facts are independent of application policy at S8."""

from uuid import uuid4

import pytest

from shared.authorization import CredentialCeiling, TargetRef
from shared.credentials import CredentialContext
from shared.models import AuditLog
from tests.workspaces.test_account_policy_admin import Provider, _actor
from workspaces import services
from workspaces.models import (
    AccountMembership,
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
    WorkspaceOwnership,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def hierarchy():
    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id)
    workspace = Workspace.objects.get(organization=organization)
    return account, organization, workspace


@pytest.mark.parametrize("kind", ["human", "service"])
@pytest.mark.parametrize("target_type", ["organization", "workspace"])
def test_admin_records_and_removes_principal_membership_without_role_grant(hierarchy, kind, target_type):
    account, organization, workspace = hierarchy
    target = organization if target_type == "organization" else workspace
    actor = _actor(kind, actions=frozenset({f"{target_type}.manage_members"}))
    subject = _actor("service").principal
    provider = Provider(allowed_targets=frozenset({target.uuid}))

    services.admin_add_scope_member(actor, provider, target_type, target.uuid, subject)
    services.admin_add_scope_member(actor, provider, target_type, target.uuid, subject)
    page = services.admin_list_scope_members(actor, provider, target_type, target.uuid)
    assert page.count == 1
    assert page.results[0].principal_uuid == subject.uuid
    model = OrganizationMembership if target_type == "organization" else WorkspaceMembership
    row = model.objects.get(principal_uuid=subject.uuid)
    assert row.user_id is None
    assert row.role == ""
    assert not AccountMembership.objects.filter(account_id=account.id).exists()
    assert AuditLog.objects.filter(actor_principal_uuid=actor.principal.uuid, action="create").exists()

    services.admin_remove_scope_member(actor, provider, target_type, target.uuid, subject.uuid)
    assert services.admin_list_scope_members(actor, provider, target_type, target.uuid).count == 0


def test_scope_membership_denial_ceiling_archive_and_provider_loss_have_no_effect(hierarchy):
    _, _, workspace = hierarchy
    actor = _actor("service", actions=frozenset({"workspace.manage_members"}))
    subject = _actor("service").principal
    sibling = services.create_account(kind="team", name="Other")
    other = Workspace.objects.get(organization__account_id=sibling.id)

    class LostProvider(Provider):
        def check(self, request):
            raise ConnectionError("provider unavailable")

    for provider in (Provider(allowed=False), LostProvider()):
        with pytest.raises(services.AccountScopeError):
            services.admin_add_scope_member(actor, provider, "workspace", workspace.uuid, subject)
    restricted = CredentialContext(
        actor.principal,
        "service",
        uuid4(),
        CredentialCeiling(actor.ceiling.actions, TargetRef("workspace", workspace.uuid)),
        frozenset(),
    )
    with pytest.raises(services.AccountScopeError):
        services.admin_add_scope_member(restricted, Provider(), "workspace", other.uuid, subject)
    assert not WorkspaceMembership.objects.filter(principal_uuid=subject.uuid).exists()


def test_owner_is_separate_from_membership_and_cannot_be_removed(hierarchy):
    _, _, workspace = hierarchy
    actor = _actor("service", actions=frozenset({"workspace.manage_members", "workspace.transfer"}))
    source = _actor("service").principal
    destination = _actor("service").principal
    for principal in (source, destination):
        services.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, principal)
    WorkspaceOwnership.objects.create(workspace=workspace, principal_uuid=source.uuid)

    with pytest.raises(services.AccountScopeError):
        services.admin_remove_scope_member(actor, Provider(), "workspace", workspace.uuid, source.uuid)
    services.admin_transfer_workspace_principal(actor, Provider(), workspace.uuid, source.uuid, destination.uuid)
    workspace.refresh_from_db()
    assert workspace.ownerships.get().principal_uuid == destination.uuid
    assert WorkspaceMembership.objects.filter(workspace=workspace, principal_uuid=source.uuid).exists()
    with pytest.raises(services.AccountScopeError):
        services.admin_transfer_workspace_principal(actor, Provider(), workspace.uuid, source.uuid, destination.uuid)


def test_membership_audit_failure_rolls_back(hierarchy, monkeypatch):
    _, _, workspace = hierarchy
    actor = _actor("service", actions=frozenset({"workspace.manage_members"}))
    subject = _actor("service").principal

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("workspaces.services._policy_memberships.audit_log", fail_audit)
    with pytest.raises(RuntimeError):
        services.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, subject)
    assert not WorkspaceMembership.objects.filter(principal_uuid=subject.uuid).exists()


def test_explicit_multiple_owners_preserve_last_owner_without_policy_grants(hierarchy):
    _, _, workspace = hierarchy
    actor = _actor("service", actions=frozenset({"workspace.manage_members", "workspace.transfer"}))
    first, second = _actor("service").principal, _actor("human").principal
    for principal in (first, second):
        services.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, principal)
        services.admin_add_workspace_owner(actor, Provider(), workspace.uuid, principal.uuid)
    assert workspace.ownerships.count() == 2
    assert set(WorkspaceMembership.objects.filter(workspace=workspace).values_list("role", flat=True)) == {""}
    services.admin_remove_workspace_owner(actor, Provider(), workspace.uuid, first.uuid)
    with pytest.raises(services.AccountScopeError):
        services.admin_remove_workspace_owner(actor, Provider(), workspace.uuid, second.uuid)
    assert workspace.ownerships.count() == 1


def test_principal_self_membership_and_leave_preserve_last_owner(hierarchy):
    actor = _actor(
        "service",
        actions=frozenset({"workspace.manage_members", "workspace.transfer", "workspace.read", "workspace.leave"}),
    )
    _, _, workspace = hierarchy
    services.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, actor.principal)
    assert (
        services.policy_self_workspace_membership(actor, Provider(), workspace.uuid).principal_uuid
        == actor.principal.uuid
    )
    services.admin_add_workspace_owner(actor, Provider(), workspace.uuid, actor.principal.uuid)
    with pytest.raises(services.WorkspaceMembershipError):
        services.policy_leave_workspace(actor, Provider(), workspace.uuid)
    other = _actor("service").principal
    services.admin_add_scope_member(actor, Provider(), "workspace", workspace.uuid, other)
    services.admin_add_workspace_owner(actor, Provider(), workspace.uuid, other.uuid)
    services.policy_leave_workspace(actor, Provider(), workspace.uuid)
    assert not WorkspaceMembership.objects.filter(workspace=workspace, principal_uuid=actor.principal.uuid).exists()
    assert WorkspaceOwnership.objects.get(workspace=workspace).principal_uuid == other.uuid
