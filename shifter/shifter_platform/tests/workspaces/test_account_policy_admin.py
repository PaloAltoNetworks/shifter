"""Policy-aware account administration prepared for the S8 authority cutover."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from management.models import Principal
from shared.audit import RequestAudit
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog
from workspaces import services
from workspaces.models import Account, AccountMembership, Organization, Workspace

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, *, allowed: bool = True, allowed_targets: frozenset | None = None):
        self.allowed = allowed
        self.allowed_targets = allowed_targets
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        permitted = self.allowed and (self.allowed_targets is None or request.target.uuid in self.allowed_targets)
        return AuthorizationDecision(
            DecisionKind.ALLOWED if permitted else DecisionKind.DENIED,
            "policy_allowed" if permitted else "policy_denied",
        )

    def batch_check(self, requests):
        return tuple(self.check(request) for request in requests)


def _actor(kind="human", actions=frozenset({"installation.manage_accounts", "account.manage_organizations"})):
    if kind == "human":
        user = get_user_model().objects.create_user(username=f"user-{uuid4()}")
        principal = Principal.objects.get(user=user)
    else:
        principal = Principal.objects.create(uuid=uuid4(), kind="service", name="Administrator")
    ref = PrincipalRef(principal.uuid, kind)
    return CredentialContext(
        ref, "session" if kind == "human" else "service", uuid4(), CredentialCeiling(actions), frozenset()
    )


@pytest.mark.parametrize("kind", ["human", "service"])
def test_full_administrator_creates_business_account_without_implicit_grants(kind):
    actor = _actor(kind)
    provider = Provider()

    account = services.admin_create_account(actor, provider, kind="team", name="Customer")

    assert account.kind == "team"
    assert Organization.objects.filter(account_id=account.id, is_default=True).count() == 1
    assert Workspace.objects.filter(organization__account_id=account.id, is_default=True).count() == 1
    assert not AccountMembership.objects.filter(account_id=account.id).exists()
    request = provider.requests[0]
    assert request.principal == actor.principal
    assert request.action == "installation.manage_accounts"
    assert request.target.type == "installation"
    assert (
        AuditLog.objects.get(entity_type="account", entity_id=account.id).actor_principal_uuid == actor.principal.uuid
    )


def test_account_creation_carries_request_attribution_into_structural_defaults():
    actor = _actor("service")
    audit = RequestAudit(source_ip="127.0.0.1", user_agent="test-client", request_id="account-request")

    account = services.admin_create_account(actor, Provider(), kind="team", name="Customer", audit=audit)

    events = AuditLog.objects.filter(context="account_hierarchy", actor_principal_uuid=actor.principal.uuid)
    assert events.count() == 3
    assert all(event.request_id == "account-request" for event in events)
    assert all(event.source_ip == "127.0.0.1" for event in events)
    assert events.filter(entity_type="account", entity_id=account.id).exists()


def test_provider_denial_and_credential_ceiling_prevent_account_creation():
    actor = _actor()
    with pytest.raises(services.AccountScopeError):
        services.admin_create_account(actor, Provider(allowed=False), kind="team", name="Denied")
    with pytest.raises(services.AccountScopeError):
        services.admin_create_account(
            _actor(actions=frozenset({"account.manage_organizations"})), Provider(), kind="team", name="Ceiling"
        )
    assert not Account.objects.filter(name__in=("Denied", "Ceiling")).exists()


def test_account_admin_cannot_create_sibling_organization_and_individual_has_no_subdivisions():
    actor = _actor()
    first = services.create_account(kind="team", name="First")
    second = services.create_account(kind="team", name="Second")
    provider = Provider()

    organization = services.admin_create_organization(actor, provider, first.uuid, name="Extra")
    assert organization.account_id == first.id
    assert provider.requests[-1].scope.account_uuid == first.uuid

    individual = services.create_account(kind="individual", name="Person", owner=actor.principal)
    with pytest.raises(services.AccountScopeError):
        services.admin_create_organization(actor, provider, individual.uuid, name="Invalid")
    assert not Organization.objects.filter(account_id=individual.id).exists()
    assert not Organization.objects.filter(account_id=second.id, name="Extra").exists()


def test_account_list_filters_before_count_and_pagination():
    first = services.create_account(kind="team", name="First")
    services.create_account(kind="team", name="Hidden")
    last = services.create_account(kind="team", name="Last")
    actor = _actor(actions=frozenset({"account.read"}))
    provider = Provider(allowed_targets=frozenset({first.uuid, last.uuid}))

    page = services.admin_list_accounts(actor, provider, offset=1, limit=1)

    assert page.count == 2
    assert len(page.results) == 1
    assert page.results[0].uuid == last.uuid
    assert page.results[0].name == "Last"
    assert {request.action for request in provider.requests} == {"account.read"}


def test_account_list_fails_closed_on_incomplete_batch_or_evaluator_error():
    services.create_account(kind="team", name="First")
    actor = _actor(actions=frozenset({"account.read"}))

    class Incomplete(Provider):
        def batch_check(self, requests):
            return ()

    with pytest.raises(services.AccountScopeError):
        services.admin_list_accounts(actor, Incomplete(), offset=0, limit=10)


def test_account_list_honors_exact_credential_target_before_batch_checks():
    first = services.create_account(kind="team", name="First")
    services.create_account(kind="team", name="Hidden")
    unrestricted = _actor(actions=frozenset({"account.read"}))
    actor = CredentialContext(
        unrestricted.principal,
        "personal",
        uuid4(),
        CredentialCeiling(frozenset({"account.read"}), TargetRef("account", first.uuid)),
        frozenset(),
    )

    page = services.admin_list_accounts(actor, Provider(), offset=0, limit=10)

    assert page.count == 1
    assert [item.uuid for item in page.results] == [first.uuid]


def test_organization_list_filters_siblings_before_count_and_page():
    account = services.create_account(kind="team", name="Customer")
    first = Organization.objects.get(account_id=account.id, is_default=True)
    hidden = services.create_account_organization(account.uuid, "Hidden")
    last = services.create_account_organization(account.uuid, "Visible")
    actor = _actor(actions=frozenset({"organization.read"}))
    provider = Provider(allowed_targets=frozenset({first.uuid, last.uuid}))

    page = services.admin_list_organizations(actor, provider, account.uuid, offset=1, limit=1)

    assert page.count == 2
    assert [item.uuid for item in page.results] == [last.uuid]
    assert hidden.uuid not in [item.uuid for item in page.results]
    assert {request.action for request in provider.requests} == {"organization.read"}


def test_workspace_list_filters_siblings_and_rejects_cross_account_parent():
    account = services.create_account(kind="team", name="Customer")
    other = services.create_account(kind="team", name="Other")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    first = Workspace.objects.get(organization=organization, is_default=True)
    hidden = services.create_account_workspace(account.uuid, organization.uuid, "Hidden")
    last = services.create_account_workspace(account.uuid, organization.uuid, "Visible")
    actor = _actor(actions=frozenset({"workspace.read"}))
    provider = Provider(allowed_targets=frozenset({first.uuid, last.uuid}))

    page = services.admin_list_workspaces(actor, provider, account.uuid, organization.uuid, offset=1, limit=1)

    assert page.count == 2
    assert [item.uuid for item in page.results] == [last.uuid]
    assert hidden.uuid not in [item.uuid for item in page.results]
    with pytest.raises(services.AccountScopeError):
        services.admin_list_workspaces(actor, provider, other.uuid, organization.uuid)


def test_detail_reads_require_exact_target_policy_and_valid_parent():
    account = services.create_account(kind="team", name="Customer")
    other = services.create_account(kind="team", name="Other")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.get(organization=organization, is_default=True)
    actor = _actor(actions=frozenset({"account.read", "organization.read", "workspace.read"}))
    provider = Provider(allowed_targets=frozenset({account.uuid, organization.uuid, workspace.uuid}))

    assert services.admin_get_account(actor, provider, account.uuid).uuid == account.uuid
    assert services.admin_get_organization(actor, provider, account.uuid, organization.uuid).uuid == organization.uuid
    result = services.admin_get_workspace(actor, provider, account.uuid, organization.uuid, workspace.uuid)
    assert result.uuid == workspace.uuid
    with pytest.raises(services.AccountScopeError):
        services.admin_get_account(actor, provider, other.uuid)
    with pytest.raises(services.AccountScopeError):
        services.admin_get_organization(actor, provider, other.uuid, organization.uuid)
    with pytest.raises(services.AccountScopeError):
        services.admin_get_workspace(actor, provider, other.uuid, organization.uuid, workspace.uuid)


def test_individual_account_is_resolved_without_subdivision_selector():
    actor = _actor(actions=frozenset({"account.read"}))
    account = services.create_account(kind="individual", name="Personal", owner=actor.principal)

    current = services.admin_individual_account(actor, Provider())

    assert current.uuid == account.uuid
    assert current.kind == "individual"
    assert not Organization.objects.filter(account_id=account.id).exists()


def test_account_membership_requires_exact_policy_and_active_subject():
    account = services.create_account(kind="team", name="Customer")
    sibling = services.create_account(kind="team", name="Sibling")
    actor = _actor(actions=frozenset({"account.manage_members"}))
    member = _actor("service").principal
    provider = Provider(allowed_targets=frozenset({account.uuid}))

    services.admin_add_account_member(actor, provider, account.uuid, member)

    assert AccountMembership.objects.filter(account_id=account.id, principal_uuid=member.uuid).exists()
    with pytest.raises(services.AccountScopeError):
        services.admin_add_account_member(actor, provider, sibling.uuid, member)
    with pytest.raises(services.AccountScopeError):
        services.admin_add_account_member(actor, provider, account.uuid, PrincipalRef(uuid4(), "service"))
    assert not AccountMembership.objects.filter(account_id=sibling.id).exists()


def test_account_membership_list_and_remove_use_parent_policy_and_strict_audit():
    account = services.create_account(kind="team", name="Customer")
    other = services.create_account(kind="team", name="Other")
    actor = _actor("service", actions=frozenset({"account.manage_members"}))
    member = _actor("service").principal
    services.add_account_member(account.uuid, member)
    services.add_account_member(other.uuid, member)
    provider = Provider(allowed_targets=frozenset({account.uuid}))

    page = services.admin_list_account_members(actor, provider, account.uuid)
    assert page.count == 1
    assert [item.principal_uuid for item in page.results] == [member.uuid]
    with pytest.raises(services.AccountScopeError):
        services.admin_list_account_members(actor, provider, other.uuid)

    services.admin_remove_account_member(actor, provider, account.uuid, member.uuid)
    assert not AccountMembership.objects.filter(account_id=account.id, principal_uuid=member.uuid).exists()
    assert AccountMembership.objects.filter(account_id=other.id, principal_uuid=member.uuid).exists()
    assert AuditLog.objects.filter(
        entity_type="account_membership", action="delete", actor_principal_uuid=actor.principal.uuid
    ).exists()


@pytest.mark.parametrize("kind", ["human", "service"])
def test_account_http_adapter_admits_policy_admin_and_rejects_unknown_fields(monkeypatch, kind):
    from workspaces.api.account_admin_views import AccountCollectionView

    actor = _actor(kind)
    provider = Provider()
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", lambda: provider)
    view = AccountCollectionView.as_view()
    request = APIRequestFactory().post("/api/v1/accounts/", {"kind": "team", "name": "Customer"}, format="json")
    if kind == "human":
        user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
        force_authenticate(request, user=user)
    else:
        request.credential_context = actor
        force_authenticate(request, token=actor)

    response = view(request)

    assert response.status_code == 201
    assert response.data["kind"] == "team"
    assert "id" not in response.data
    assert Account.objects.filter(uuid=response.data["uuid"]).exists()
    assert provider.requests[0].action == "installation.manage_accounts"

    invalid = APIRequestFactory().post(
        "/api/v1/accounts/", {"kind": "team", "name": "Other", "is_superuser": True}, format="json"
    )
    if kind == "human":
        force_authenticate(invalid, user=user)
    else:
        invalid.credential_context = actor
        force_authenticate(invalid, token=actor)
    assert view(invalid).status_code == 400


def test_account_http_adapter_checks_parent_scope_for_workspace_creation(monkeypatch):
    from workspaces.api.account_admin_views import AccountWorkspaceCollectionView

    actor = _actor(actions=frozenset({"organization.manage_workspaces"}))
    first = services.create_account(kind="team", name="First")
    second = services.create_account(kind="team", name="Second")
    organization = Organization.objects.get(account_id=second.id, is_default=True)
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().post("/api/v1/accounts/workspaces/", {"name": "Nope"}, format="json")
    user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
    force_authenticate(request, user=user)

    response = AccountWorkspaceCollectionView.as_view()(
        request, account_uuid=first.uuid, organization_uuid=organization.uuid
    )

    assert response.status_code == 403
    assert not Workspace.objects.filter(organization=organization, name="Nope").exists()


def test_account_http_adapter_creates_real_organization_but_no_individual_subdivision(monkeypatch):
    from workspaces.api.account_admin_views import AccountOrganizationCollectionView

    actor = _actor(actions=frozenset({"account.manage_organizations"}))
    team = services.create_account(kind="team", name="Team")
    individual = services.create_account(kind="individual", name="Person", owner=actor.principal)
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)
    user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
    view = AccountOrganizationCollectionView.as_view()

    valid = APIRequestFactory().post("/api/v1/accounts/organizations/", {"name": "Division"}, format="json")
    force_authenticate(valid, user=user)
    created = view(valid, account_uuid=team.uuid)
    assert created.status_code == 201
    assert Organization.objects.filter(uuid=created.data["uuid"], account_id=team.id).exists()

    invalid = APIRequestFactory().post("/api/v1/accounts/organizations/", {"name": "Nope"}, format="json")
    force_authenticate(invalid, user=user)
    assert view(invalid, account_uuid=individual.uuid).status_code == 403
    assert not Organization.objects.filter(account_id=individual.id).exists()


def test_account_http_adapter_adds_active_member_without_policy_grant(monkeypatch):
    from workspaces.api.account_admin_views import AccountMemberCollectionView

    actor = _actor(actions=frozenset({"account.manage_members"}))
    subject = _actor("service").principal
    account = services.create_account(kind="team", name="Team")
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().post(
        "/api/v1/accounts/members/", {"principal_uuid": str(subject.uuid), "principal_kind": "service"}, format="json"
    )
    user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
    force_authenticate(request, user=user)

    response = AccountMemberCollectionView.as_view()(request, account_uuid=account.uuid)

    assert response.status_code == 204
    assert AccountMembership.objects.filter(account_id=account.id, principal_uuid=subject.uuid).exists()


def test_organization_http_list_count_excludes_denied_sibling(monkeypatch):
    from workspaces.api.account_admin_views import AccountOrganizationCollectionView

    actor = _actor(actions=frozenset({"organization.read"}))
    account = services.create_account(kind="team", name="Team")
    visible = Organization.objects.get(account_id=account.id, is_default=True)
    services.create_account_organization(account.uuid, "Hidden")
    provider = Provider(allowed_targets=frozenset({visible.uuid}))
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", lambda: provider)
    user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
    request = APIRequestFactory().get("/api/v1/accounts/organizations/")
    force_authenticate(request, user=user)

    response = AccountOrganizationCollectionView.as_view()(request, account_uuid=account.uuid)

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert [row["uuid"] for row in response.data["results"]] == [str(visible.uuid)]
