"""Prepared account/profile/usage administration retains owning validation."""

import pytest

from shared.authorization import APPLICATION_ADMINISTRATOR_ACTIONS
from tests.workspaces.test_account_policy_admin import Provider, _actor
from workspaces import services
from workspaces.models import Account, Organization, Workspace

pytestmark = pytest.mark.django_db


def test_full_admin_ceiling_includes_hierarchy_discovery():
    assert {"account.read", "organization.read", "workspace.read"}.issubset(APPLICATION_ADMINISTRATOR_ACTIONS)


@pytest.mark.parametrize("kind", ["human", "service"])
def test_profile_updates_use_exact_scope_and_keep_kind_and_ancestry(kind):
    actor = _actor(kind, actions=frozenset({"account.update", "organization.update", "organization.read"}))
    account = services.create_account(kind="team", name="Team")
    organization = Organization.objects.get(account_id=account.id)
    services.admin_update_account(actor, Provider(), account.uuid, {"name": "Renamed"})
    assert Account.objects.get(uuid=account.uuid).name == "Renamed"
    result = services.admin_update_organization_profile(
        actor,
        Provider(),
        account.uuid,
        organization.uuid,
        {"name": "Division", "support_email": "help@example.test"},
    )
    assert result.name == "Division"
    assert result.support_email == "help@example.test"
    with pytest.raises(services.AccountScopeError):
        services.admin_update_account(actor, Provider(), account.uuid, {"kind": "individual"})
    other = services.create_account(kind="team", name="Other")
    with pytest.raises(services.AccountScopeError):
        services.admin_update_organization_profile(actor, Provider(), other.uuid, organization.uuid, {"name": "Wrong"})
    assert Organization.objects.get(uuid=organization.uuid).name == "Division"


def test_quota_read_and_search_exclude_other_scopes():
    account = services.create_account(kind="team", name="Visible")
    services.create_account(kind="team", name="Hidden")
    workspace = Workspace.objects.get(organization__account_id=account.id)
    actor = _actor("service", actions=frozenset({"account.read", "workspace.read"}))
    page = services.admin_list_accounts(actor, Provider(allowed_targets=frozenset({account.uuid})), search="Visible")
    assert page.count == 1 and page.results[0].uuid == account.uuid
    result = services.admin_workspace_quota_usage(actor, Provider(), workspace.uuid)
    assert result.workspace_uuid == workspace.uuid
    with pytest.raises(services.AccountScopeError):
        services.admin_workspace_quota_usage(actor, Provider(allowed=False), workspace.uuid)


def test_archived_workspace_discovery_is_explicit_and_retains_scope_policy():
    from django.utils import timezone

    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id)
    row = services.create_account_workspace(account.uuid, organization.uuid, "Archived")
    workspace = Workspace.objects.get(uuid=row.uuid)
    workspace.archived_at = timezone.now()
    workspace.save(update_fields=["archived_at"])
    actor = _actor("service", actions=frozenset({"workspace.read"}))
    provider = Provider(allowed_targets=frozenset({workspace.uuid}))
    assert services.admin_list_workspaces(actor, provider, account.uuid, organization.uuid).count == 0
    page = services.admin_list_workspaces(
        actor, provider, account.uuid, organization.uuid, filters=services.WorkspaceAdminFilters(include_archived=True)
    )
    assert page.count == 1 and page.results[0].archived_at is not None


def test_principal_context_uses_policy_and_individual_scope_without_membership_inference():
    actor = _actor("human", actions=frozenset({"account.read"}))
    account = services.create_account(kind="individual", name="Personal", owner=actor.principal)
    context = services.admin_principal_context(actor, Provider())
    assert context.principal_uuid == actor.principal.uuid
    assert context.individual_account.uuid == account.uuid
    assert context.installation_actions == ()
    service = _actor("service", actions=frozenset({"installation.manage_principals"}))
    context = services.admin_principal_context(service, Provider())
    assert context.individual_account is None
    assert context.installation_actions == ("installation.manage_principals",)


def test_workspace_search_filters_before_authorized_count_and_page():
    actor = _actor("service", actions=frozenset({"workspace.read"}))
    account = services.create_account(kind="team", name="Search")
    organization = Organization.objects.get(account_id=account.id)
    visible = services.create_account_workspace(account.uuid, organization.uuid, "Matching visible")
    services.create_account_workspace(account.uuid, organization.uuid, "Matching hidden")
    page = services.admin_list_workspaces(
        actor,
        Provider(allowed_targets=frozenset({visible.uuid})),
        account.uuid,
        organization.uuid,
        filters=services.WorkspaceAdminFilters(search="Matching"),
    )
    assert page.count == 1 and page.results[0].uuid == visible.uuid
