from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from management.models import Principal
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import AUTHORIZATION_ACTION_SCOPES
from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.authorization import AuthorizationDecision, AuthorizationProviderError, DecisionKind, RelationshipState
from shared.models import AuditLog
from workspaces.api import authorization_views
from workspaces.models import Account, Organization, Workspace

pytestmark = pytest.mark.django_db


class FakeProvider:
    model_id = "01J00000000000000000000000"
    store_id = "01J00000000000000000000001"

    def __init__(self) -> None:
        self.changes: list[object] = []
        self.allowed = True
        self.denied_actions: set[str] = set()
        self.checked_actions: list[str] = []
        self.write_error = False
        self.state = RelationshipState(grant_present=True, deny_present=False)

    def check(self, request):
        self.checked_actions.append(request.action)
        if self.allowed and request.action not in self.denied_actions:
            return AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")
        return AuthorizationDecision(DecisionKind.DENIED, "policy_denied")

    def batch_check(self, requests):
        return tuple(self.check(item) for item in requests)

    def write_relationships(self, change):
        self.changes.append(change)
        if self.write_error:
            raise AuthorizationProviderError("OpenFGA relationship write failed")

    def read_relationships(self, change):
        return self.state


@pytest.fixture
def authorization_context(monkeypatch, settings):
    user = get_user_model().objects.create_user(username="authorization-admin", password="test-pass")
    principal = user.identity_principal
    service = Principal.objects.create(kind=Principal.Kind.SERVICE, name="automation")
    account = Account.objects.create(kind=Account.Kind.TEAM, name="Account")
    organization = Organization.objects.create(account=account, name="Organization")
    workspace = Workspace.objects.create(organization=organization, name="Workspace")
    provider = FakeProvider()
    settings.OPENFGA_MODEL_ID = "01J00000000000000000000000"
    monkeypatch.setattr(authorization_views, "configured_authorization_provider", lambda: provider)
    from shared.authorization import port

    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    return user, principal, service, workspace, provider


def _url(workspace: Workspace, suffix: str) -> str:
    return f"/api/v1/workspaces/{workspace.uuid}/authorization/{suffix}"


def test_native_service_authorization_writes_preserve_canonical_actor(authorization_context, monkeypatch, settings):
    from config import service_identity
    from management import services
    from management.models import ProviderBinding, ServiceCredentialAdmission
    from shared.audit.integrity import verify_audit_chain
    from workspaces.models import AuthorizationOperation

    _user, _human, service, workspace, _provider = authorization_context
    principal = services.resolve_principal_uuid(service.uuid)
    settings.GCP_SERVICE_TOKEN_AUDIENCE = "https://portal.example.test"
    subject = "123456789012345678901"
    services.bind_principal_provider_identity(principal, "https://accounts.google.com", subject)
    ServiceCredentialAdmission.objects.create(
        binding=ProviderBinding.objects.get(principal=service),
        audience=settings.GCP_SERVICE_TOKEN_AUDIENCE,
        scopes=list(AUTHORIZATION_ACTION_SCOPES.values()),
    )
    claims = {
        "iss": "https://accounts.google.com",
        "sub": subject,
        "aud": settings.GCP_SERVICE_TOKEN_AUDIENCE,
        "email": "operator@synthetic.iam.gserviceaccount.com",
        "email_verified": True,
    }
    monkeypatch.setattr(service_identity.id_token, "verify_oauth2_token", lambda *_args, **_kwargs: claims)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer header.payload.signature", HTTP_X_REQUEST_ID="service-write")
    created = client.post(_url(workspace, "groups/"), {"name": "Service operators"}, format="json")
    assert created.status_code == 201
    operation = client.post(
        _url(workspace, f"groups/{created.json()['uuid']}/memberships/"),
        {"principal_uuid": str(_human.uuid), "effect": "grant", "idempotency_key": str(uuid4())},
        format="json",
    )
    assert operation.status_code == 202
    assert operation.json()["state"] == "confirmed"
    rows = list(AuditLog.objects.filter(request_id="service-write"))
    assert len(rows) == 3
    assert all(row.actor_type == "principal" and row.actor_id is None for row in rows)
    assert all(row.actor_principal_uuid == service.uuid for row in rows)
    assert (
        AuthorizationOperation.objects.get(id=operation.json()["operation_id"]).audit_actor_principal_uuid
        == service.uuid
    )
    verify_audit_chain()

    # The registered reverse migration cannot silently erase journal identity.
    from importlib import import_module

    from django.db import connection
    from django.db.migrations.exceptions import IrreversibleError
    from django.db.migrations.executor import MigrationExecutor

    migration = import_module("workspaces.migrations.0019_principal_audit_attribution").Migration
    state = MigrationExecutor(connection).loader.project_state()
    with pytest.raises(IrreversibleError):
        migration.operations[-1].database_backwards("workspaces", connection.schema_editor(), state, state)


def test_personal_credential_cannot_cross_its_issuance_target(authorization_context):
    from django.utils import timezone

    user, _principal, _service, workspace, _provider = authorization_context
    other = Workspace.objects.create(organization=workspace.organization, name="Other workspace")
    client = APIClient()
    client.force_login(user, backend="config.auth.PlatformModelBackend")
    response = client.post(
        "/api/v1/credentials/personal/",
        {
            "name": "One workspace",
            "scopes": ["authorization:workspace.manage_authorization"],
            "expires_at": (timezone.now() + timezone.timedelta(hours=1)).isoformat(),
            "target_type": "workspace",
            "target_uuid": str(workspace.uuid),
        },
        format="json",
    )
    assert response.status_code == 201
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['token']}")
    assert client.get(_url(workspace, "groups/")).status_code == 200
    assert client.get(_url(other, "groups/")).status_code == 403


def test_catalog_is_closed_and_contains_no_provider_contract(authorization_context) -> None:
    user, _principal, _service, _workspace, _provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/authorization/catalog/")

    assert response.status_code == 200
    assert any(item["code"] == "workspace.manage_authorization" for item in response.json())
    assert "relation" not in response.content.decode()

    predefined = client.get("/api/v1/workspaces/authorization/predefined-catalog/")
    assert predefined.status_code == 200
    application = next(item for item in predefined.json() if item["code"] == "application_administrator")
    assert application["target_type"] == "installation"
    assert "relation" not in application


def test_group_creation_and_service_membership_return_bounded_operations(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)
    created = client.post(
        _url(workspace, "groups/"),
        {"name": "Operators", "description": "Scoped operators"},
        format="json",
        HTTP_X_REQUEST_ID="metadata-request",
        HTTP_USER_AGENT="authorization-test",
    )

    response = client.post(
        _url(workspace, f"groups/{created.json()['uuid']}/memberships/"),
        {
            "principal_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert created.status_code == 201
    assert response.status_code == 202
    assert response.json()["state"] == "confirmed"
    assert set(response.json()) == {"operation_id", "state"}
    assert provider.changes
    metadata_audit = AuditLog.objects.get(
        entity_type=AuditEntityType.AUTHORIZATION_GROUP,
        action=AuditAction.CREATE,
    )
    assert metadata_audit.actor_type == AuditActorType.USER
    assert metadata_audit.actor_id == user.id
    assert metadata_audit.actor_principal_uuid == _principal.uuid
    assert metadata_audit.request_id == "metadata-request"
    assert metadata_audit.user_agent == "authorization-test"


def test_api_token_operation_audit_uses_token_attribution_not_principal_kind(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    token, raw = ApiToken.create_token(
        name="authorization-audit",
        created_by=user,
        scopes=[
            AUTHORIZATION_ACTION_SCOPES["workspace.read"],
            AUTHORIZATION_ACTION_SCOPES["workspace.manage_authorization"],
        ],
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}", HTTP_X_REQUEST_ID="token-request")

    response = client.post(
        _url(workspace, "direct-assignments/"),
        {
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "action": "workspace.read",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert response.status_code == 202
    assert response.json()["state"] == "confirmed"
    requested = AuditLog.objects.get(action=AuditAction.AUTHORIZATION_REQUESTED)
    confirmed = AuditLog.objects.get(action=AuditAction.AUTHORIZATION_CONFIRMED)
    assert {requested.actor_type, confirmed.actor_type} == {AuditActorType.APIKEY}
    assert {requested.actor_id, confirmed.actor_id} == {token.id}
    assert {requested.actor_principal_uuid, confirmed.actor_principal_uuid} == {_principal.uuid}
    assert {requested.request_id, confirmed.request_id} == {"token-request"}
    assert provider.changes


def test_operation_get_is_observational_and_reconciliation_requires_csrf_protected_post(
    authorization_context,
) -> None:
    user, _principal, service, workspace, provider = authorization_context
    creator = APIClient()
    creator.force_authenticate(user=user)
    provider.write_error = True
    mutation = creator.post(
        _url(workspace, "direct-assignments/"),
        {
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "action": "workspace.read",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )
    operation_url = _url(workspace, f"operations/{mutation.json()['operation_id']}/")
    provider.changes.clear()

    observed = creator.get(operation_url)

    assert mutation.json()["state"] == "unresolved"
    assert observed.status_code == 200
    assert observed.json()["state"] == "unresolved"
    assert provider.changes == []

    session = APIClient(enforce_csrf_checks=True)
    assert session.login(username=user.username, password="test-pass")
    rejected = session.post(operation_url, {}, format="json")
    assert rejected.status_code == 403

    provider.write_error = False
    session.cookies["csrftoken"] = "a" * 32
    reconciled = session.post(operation_url, {}, format="json", HTTP_X_CSRFTOKEN="a" * 32)
    assert reconciled.status_code == 200
    assert reconciled.json()["state"] == "confirmed"


@pytest.mark.parametrize("denial", ["credential", "policy"])
def test_reconciliation_reauthorizes_the_original_effect(authorization_context, denial) -> None:
    user, _principal, service, workspace, provider = authorization_context
    creator = APIClient()
    creator.force_authenticate(user=user)
    provider.write_error = True
    mutation = creator.post(
        _url(workspace, "direct-assignments/"),
        {
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "action": "workspace.read",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )
    assert mutation.json()["state"] == "unresolved"
    scopes = [AUTHORIZATION_ACTION_SCOPES["workspace.manage_authorization"]]
    if denial == "policy":
        scopes.append(AUTHORIZATION_ACTION_SCOPES["workspace.read"])
        provider.denied_actions.add("workspace.read")
    _token, raw = ApiToken.create_token(name="limited-recovery", created_by=user, scopes=scopes)
    limited = APIClient()
    limited.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    operation_url = _url(workspace, f"operations/{mutation.json()['operation_id']}/")
    provider.changes.clear()
    provider.write_error = False

    assert limited.get(operation_url).status_code == 200
    assert limited.post(operation_url, {}, format="json").status_code == 403
    assert provider.changes == []


def test_unknown_fields_and_unknown_actions_are_rejected(authorization_context) -> None:
    user, _principal, service, workspace, _provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)

    metadata = client.post(
        _url(workspace, "groups/"),
        {"name": "Operators", "provider_relation": "administrator"},
        format="json",
    )
    action = client.post(
        _url(workspace, "direct-assignments/"),
        {
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "action": "workspace.not_registered",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert metadata.status_code == 400
    assert action.status_code == 400
    assert "provider_relation" not in action.content.decode()


def test_duplicate_json_members_are_rejected_before_serializer_validation(authorization_context) -> None:
    user, _principal, _service, workspace, _provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.generic(
        "POST",
        _url(workspace, "groups/"),
        '{"name":"Operators","name":"Administrators"}',
        content_type="application/json",
    )

    assert response.status_code == 400


def test_action_routes_publish_distinct_subject_contracts(authorization_context) -> None:
    user, _principal, service, workspace, _provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)
    policy = client.post(_url(workspace, "policies/"), {"name": "Readers"}, format="json")
    common = {
        "action": "workspace.read",
        "effect": "grant",
        "idempotency_key": str(uuid4()),
    }

    mismatched_policy_subject = client.post(
        _url(workspace, f"policies/{policy.json()['uuid']}/actions/"),
        {**common, "subject_kind": "role", "subject_uuid": str(uuid4())},
        format="json",
    )
    forbidden_direct_role = client.post(
        _url(workspace, "direct-assignments/"),
        {**common, "idempotency_key": str(uuid4()), "subject_kind": "role", "subject_uuid": str(service.uuid)},
        format="json",
    )

    assert mismatched_policy_subject.status_code == 400
    assert forbidden_direct_role.status_code == 400


def test_bearer_credential_ceiling_denies_group_escalation(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    _, raw = ApiToken.create_token(
        name="limited-authorization",
        created_by=user,
        scopes=[AUTHORIZATION_ACTION_SCOPES["workspace.manage_authorization"]],
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    created = client.post(_url(workspace, "groups/"), {"name": "Operators"}, format="json")

    response = client.post(
        _url(workspace, f"groups/{created.json()['uuid']}/memberships/"),
        {
            "principal_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert created.status_code == 201
    assert response.status_code == 202
    assert response.json()["state"] == "denied"
    assert provider.changes == []


def test_bearer_credential_ceiling_denies_group_policy_escalation(authorization_context) -> None:
    user, _principal, _service, workspace, provider = authorization_context
    _, raw = ApiToken.create_token(
        name="limited-policy-authorization",
        created_by=user,
        scopes=[AUTHORIZATION_ACTION_SCOPES["workspace.manage_authorization"]],
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    group = client.post(_url(workspace, "groups/"), {"name": "Limited group"}, format="json")
    policy = client.post(_url(workspace, "policies/"), {"name": "Elevated policy"}, format="json")

    response = client.post(
        _url(workspace, f"policies/{policy.json()['uuid']}/assignments/"),
        {
            "subject_kind": "group",
            "subject_uuid": group.json()["uuid"],
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert group.status_code == 201
    assert policy.status_code == 201
    assert response.status_code == 202
    assert response.json()["state"] == "denied"
    assert provider.changes == []


def test_predefined_workspace_administrator_assignment_is_typed_and_scoped(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        _url(workspace, "predefined-assignments/"),
        {
            "policy_code": "workspace_administrator",
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert response.status_code == 202
    assert response.json()["state"] == "confirmed"
    assert provider.changes[0].grant_tuple.relation == "direct_administrator"
    assert "workspace.update" in provider.checked_actions
    assert "workspace.read" in provider.checked_actions
    assert "workspace.leave" not in provider.checked_actions
    assert "workspace.launch_range" not in provider.checked_actions


def test_predefined_policy_uuid_is_rejected_by_both_custom_policy_routes(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)
    policies = client.get(_url(workspace, "policies/"))
    predefined = next(item for item in policies.json() if item["predefined_code"] == "workspace_administrator")

    assignment = client.post(
        _url(workspace, f"policies/{predefined['uuid']}/assignments/"),
        {
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )
    action = client.post(
        _url(workspace, f"policies/{predefined['uuid']}/actions/"),
        {
            "action": "workspace.read",
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert assignment.status_code == 202
    assert assignment.json()["state"] == "denied"
    assert action.status_code == 202
    assert action.json()["state"] == "denied"
    assert provider.changes == []


def test_predefined_assignment_requires_administrator_dominance_predicate(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    provider.denied_actions.add("workspace.delegate_authorization")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        _url(workspace, "predefined-assignments/"),
        {
            "policy_code": "workspace_administrator",
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert response.status_code == 202
    assert response.json()["state"] == "denied"
    assert "workspace.delegate_authorization" in provider.checked_actions
    assert provider.changes == []


def test_predefined_assignment_rejects_cross_scope_policy(authorization_context) -> None:
    user, _principal, service, workspace, provider = authorization_context
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        _url(workspace, "predefined-assignments/"),
        {
            "policy_code": "account_administrator",
            "subject_kind": "principal",
            "subject_uuid": str(service.uuid),
            "effect": "grant",
            "idempotency_key": str(uuid4()),
        },
        format="json",
    )

    assert response.status_code == 400
    assert provider.changes == []


def test_existing_superuser_status_never_rescues_openfga_denial(authorization_context) -> None:
    user, _principal, _service, workspace, provider = authorization_context
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])
    provider.allowed = False
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(_url(workspace, "groups/"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "authorization_denied"
