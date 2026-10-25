"""Account and organization authorization metadata use the shared scope journal."""

from uuid import uuid4

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from management.models import Principal
from shared.audit import RequestAudit
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind, RelationshipState
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef, ResourceScope
from workspaces import services
from workspaces.models import Organization

pytestmark = pytest.mark.django_db


class Provider:
    model_id = "01J00000000000000000000000"
    store_id = "01J00000000000000000000001"

    def __init__(self):
        self.requests = []
        self.changes = []

    def check(self, request):
        self.requests.append(request)
        return AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")

    def batch_check(self, requests):
        return tuple(self.check(request) for request in requests)

    def write_relationships(self, change):
        self.changes.append(change)

    def read_relationships(self, _change):
        return RelationshipState(grant_present=True, deny_present=False)


def test_account_and_organization_group_metadata_use_exact_scope_actions():
    principal = Principal.objects.create(uuid=uuid4(), kind="service", name="Administrator")
    actor = PrincipalRef(principal.uuid, "service")
    ceiling = CredentialCeiling(frozenset({"account.manage_authorization", "organization.manage_authorization"}))
    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    provider = Provider()

    account_scope = ResourceScope("account", account.uuid)
    organization_scope = ResourceScope("account", account.uuid, organization.uuid)
    first = services.create_authorization_group(
        actor, ceiling, account_scope, provider, name="Account reviewers", audit=RequestAudit()
    )
    second = services.create_authorization_group(
        actor, ceiling, organization_scope, provider, name="Organization reviewers", audit=RequestAudit()
    )

    assert first.uuid != second.uuid
    assert [request.action for request in provider.requests] == [
        "account.manage_authorization",
        "organization.manage_authorization",
    ]
    assert provider.requests[0].target.uuid == account.uuid
    assert provider.requests[1].target.uuid == organization.uuid


def test_scoped_metadata_api_admits_service_and_rejects_wrong_parent(monkeypatch):
    from workspaces.api.account_authorization_views import ScopedAuthorizationGroupCollectionView

    principal = Principal.objects.create(uuid=uuid4(), kind="service", name="Administrator")
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"organization.manage_authorization"})),
        frozenset(),
    )
    first = services.create_account(kind="team", name="First")
    second = services.create_account(kind="team", name="Second")
    organization = Organization.objects.get(account_id=first.id, is_default=True)
    provider = Provider()
    monkeypatch.setattr(
        "workspaces.api.account_authorization_views.configured_authorization_provider", lambda: provider
    )
    request = APIRequestFactory().post("/api/v1/accounts/authorization/groups/", {"name": "Reviewers"}, format="json")
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = ScopedAuthorizationGroupCollectionView.as_view()(
        request, target_type="organization", target_uuid=organization.uuid, account_uuid=first.uuid
    )
    assert response.status_code == 201
    assert provider.requests[0].action == "organization.manage_authorization"

    wrong = APIRequestFactory().get("/api/v1/accounts/authorization/groups/")
    wrong.credential_context = actor
    force_authenticate(wrong, token=actor)
    denied = ScopedAuthorizationGroupCollectionView.as_view()(
        wrong, target_type="organization", target_uuid=organization.uuid, account_uuid=second.uuid
    )
    assert denied.status_code == 403


def test_scoped_action_assignment_obeys_exact_account_and_credential_ceiling(monkeypatch, settings):
    from workspaces.api.account_authorization_views import ScopedAuthorizationDirectAssignmentView

    settings.OPENFGA_MODEL_ID = Provider.model_id
    principal = Principal.objects.create(uuid=uuid4(), kind="service", name="Administrator")
    subject = Principal.objects.create(uuid=uuid4(), kind="service", name="Recipient")
    account = services.create_account(kind="team", name="Customer")
    provider = Provider()
    monkeypatch.setattr(
        "workspaces.api.account_authorization_views.configured_authorization_provider", lambda: provider
    )
    view = ScopedAuthorizationDirectAssignmentView.as_view()

    def submit(actions):
        actor = CredentialContext(
            PrincipalRef(principal.uuid, "service"),
            "service",
            uuid4(),
            CredentialCeiling(frozenset(actions)),
            frozenset(),
        )
        request = APIRequestFactory().post(
            "/api/v1/accounts/authorization/assignments/",
            {
                "subject_kind": "principal",
                "subject_uuid": str(subject.uuid),
                "action": "account.read",
                "effect": "grant",
                "idempotency_key": str(uuid4()),
            },
            format="json",
        )
        request.credential_context = actor
        force_authenticate(request, token=actor)
        return view(request, target_type="account", target_uuid=account.uuid)

    permitted = submit({"account.read", "account.manage_authorization"})
    assert permitted.status_code == 202
    assert permitted.data["state"] == "confirmed"
    assert len(provider.changes) == 1
    assert {item.target.uuid for item in provider.requests} == {account.uuid}

    denied = submit({"account.manage_authorization"})
    assert denied.status_code == 202
    assert denied.data["state"] == "denied"
    assert len(provider.changes) == 1
