"""Prepared HTTP integration exercises admission without activating production routes."""

from uuid import uuid4

import pytest
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from tests.workspaces.test_account_policy_admin import Provider, _actor
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_prepared_routes_are_unreachable_from_production():
    with pytest.raises(Resolver404):
        resolve("/api/v1/accounts/")


@pytest.mark.parametrize("kind", ["human", "service"])
@pytest.mark.urls("config.account_admin_urls")
def test_prepared_http_profile_membership_and_quota_operations(monkeypatch, kind):
    from django.contrib.auth import get_user_model

    actor = _actor(
        kind, actions=frozenset({"account.update", "organization.update", "workspace.manage_members", "workspace.read"})
    )
    account = services.create_account(kind="team", name="Team")
    organization = Organization.objects.get(account_id=account.id)
    workspace = Workspace.objects.get(organization=organization)
    subject = _actor("service").principal
    client = APIClient()
    if kind == "human":
        client.force_authenticate(get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid))
    else:

        def authenticate(_self, request):
            request.credential_context = actor
            return None, actor

        monkeypatch.setattr("shared.api_tokens.authentication.ApiTokenAuthentication.authenticate", authenticate)
        client.credentials(HTTP_AUTHORIZATION="Bearer admitted-service")
    monkeypatch.setattr("shared.authorization.port._provider_factory", Provider)
    response = client.patch(f"/api/v1/accounts/{account.uuid}/", {"name": "New name"}, format="json")
    assert response.status_code == 200
    response = client.patch(
        f"/api/v1/accounts/{account.uuid}/organizations/{organization.uuid}/",
        {"description": "Division"},
        format="json",
    )
    assert response.status_code == 200
    response = client.post(
        f"/api/v1/workspaces/{workspace.uuid}/memberships/",
        {"principal_uuid": str(subject.uuid)},
        format="json",
    )
    assert response.status_code == 204
    assert WorkspaceMembership.objects.filter(workspace=workspace, principal_uuid=subject.uuid).exists()
    response = client.get(f"/api/v1/workspaces/{workspace.uuid}/quota/")
    assert response.status_code == 200 and response.data["workspace_uuid"] == str(workspace.uuid)
    response = client.get(f"/api/v1/accounts/{account.uuid}/organizations/{organization.uuid}/workspaces/")
    assert response.status_code == 200 and response.data["results"][0]["uuid"] == str(workspace.uuid)
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace.uuid}/memberships/",
            {"principal_uuid": str(uuid4()), "role": "owner"},
            format="json",
        ).status_code
        == 400
    )


def test_prepared_contract_is_generated_from_dormant_routes():
    import json
    from pathlib import Path

    from drf_spectacular.generators import SchemaGenerator

    expected = json.loads(Path("openapi/account-admin-prepared.json").read_text())
    schema = SchemaGenerator(urlconf="config.account_admin_urls").get_schema(public=True)
    assert json.loads(json.dumps(schema)) == expected


@pytest.mark.parametrize("kind", ["human", "service"])
@pytest.mark.urls("config.account_admin_urls")
def test_prepared_http_retained_workspace_commands_use_principal_facts(monkeypatch, kind):
    from django.contrib.auth import get_user_model

    from shared.authorization import ACTION_CATALOG

    actor = _actor(kind, actions=frozenset(item.code for item in ACTION_CATALOG))
    subject = _actor("service").principal
    client = APIClient()
    if kind == "human":
        client.force_authenticate(get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid))
    else:

        def authenticate(_self, request):
            request.credential_context = actor
            return None, actor

        monkeypatch.setattr("shared.api_tokens.authentication.ApiTokenAuthentication.authenticate", authenticate)
        client.credentials(HTTP_AUTHORIZATION="Bearer admitted-service")
    monkeypatch.setattr("shared.authorization.port._provider_factory", Provider)
    monkeypatch.setattr("workspaces.services._policy_invitations._schedule_delivery", lambda _: None)
    account = services.create_account(kind="team", name="Synthetic")
    organization = Organization.objects.get(account_id=account.id)
    base = f"/api/v1/accounts/{account.uuid}/organizations/{organization.uuid}/workspaces/"
    created = client.post(base, {"name": "Additional"}, format="json")
    assert created.status_code == 201
    workspace_uuid = created.data["uuid"]
    base = f"/api/v1/workspaces/{workspace_uuid}/"
    for principal in (actor.principal, subject):
        assert (
            client.post(base + "memberships/", {"principal_uuid": str(principal.uuid)}, format="json").status_code
            == 204
        )
    assert client.get(base + "membership/").data["principal_uuid"] == str(actor.principal.uuid)
    assert (
        client.post(base + "owners/", {"principal_uuid": str(actor.principal.uuid)}, format="json").status_code == 204
    )
    assert (
        client.post(
            base + "transfer/",
            {"source_principal_uuid": str(actor.principal.uuid), "destination_principal_uuid": str(subject.uuid)},
            format="json",
        ).status_code
        == 204
    )
    invitation = client.post(base + "invitations/", {"email": "recipient@example.test"}, format="json")
    assert invitation.status_code == 201
    invitation_uuid = invitation.data["invitation_uuid"]
    assert client.get(base + "invitations/").data["count"] == 1
    for operation in ("resend", "revoke"):
        assert client.post(base + f"invitations/{invitation_uuid}/{operation}/", {}, format="json").status_code == 200
    assert (
        client.put(
            base + "quota-policy/", {"resource": "member_seats", "mode": "enforcing", "limit": 10}, format="json"
        ).status_code
        == 200
    )
    assert client.put(base + "egress-policy/", {"egress_policy": "none"}, format="json").status_code == 200
    assert client.post(base + "rename/", {"name": "Renamed"}, format="json").status_code == 200
    assert client.post(base + "memberships/leave/", {}, format="json").status_code == 204
    assert client.post(base + "archive/", {}, format="json").status_code == 200
    assert client.post(base + "restore/", {}, format="json").status_code == 200


def test_prepared_audit_contract_advertises_bearer_and_cookie_admission():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator(urlconf="config.account_admin_urls").get_schema(public=True)
    for path in ("/api/v1/audit/", "/api/v1/audit/{id}/"):
        assert {"ApiTokenAuth": []} in schema["paths"][path]["get"]["security"]
        assert {"cookieAuth": []} in schema["paths"][path]["get"]["security"]


@pytest.mark.urls("config.account_admin_urls")
def test_standalone_organization_operation_recovery_uses_persisted_ancestry(monkeypatch, settings):
    from django.contrib.auth import get_user_model

    from management.models import Principal
    from tests.workspaces.test_authorization_api import FakeProvider

    user = get_user_model().objects.create_user(username="organization-recovery", password="test-pass")
    subject = Principal.objects.create(kind="service", name="Synthetic subject")
    account = services.create_account(kind="team", name="Synthetic account")
    organization = Organization.objects.get(account_id=account.id)
    provider = FakeProvider()
    provider.write_error = True
    settings.OPENFGA_MODEL_ID = provider.model_id
    monkeypatch.setattr("shared.authorization.port._provider_factory", lambda: provider)
    client = APIClient()
    client.force_authenticate(user)
    mutation = client.post(
        f"/api/v1/accounts/{account.uuid}/organizations/{organization.uuid}/authorization/direct-assignments/",
        {
            "subject_kind": "principal",
            "subject_uuid": str(subject.uuid),
            "action": "organization.read",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )
    assert mutation.status_code == 202 and mutation.data["state"] == "unresolved"
    operation_id = mutation.data["operation_id"]
    url = f"/api/v1/organizations/{organization.uuid}/authorization/operations/{operation_id}/"
    observed = client.get(url)
    assert observed.status_code == 200 and observed.data["state"] == "unresolved"
    provider.write_error = False
    reconciled = client.post(url, {}, format="json")
    assert reconciled.status_code == 200 and reconciled.data["state"] == "confirmed"
    other = Organization.objects.create(account=organization.account, name="Other organization")
    other_url = f"/api/v1/organizations/{other.uuid}/authorization/operations/{operation_id}/"
    assert client.get(other_url).status_code in {403, 404}
    provider.allowed = False
    assert client.get(url).status_code == 403
