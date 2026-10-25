"""Policy-aware quota authoring keeps the legacy service's atomic enforcement."""

from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from management.models import Principal
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog
from workspaces import services
from workspaces.models import (
    QUOTA_MODE_ENFORCING,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Workspace,
    WorkspaceQuotaPolicy,
)

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return AuthorizationDecision(
            DecisionKind.ALLOWED if self.allowed else DecisionKind.DENIED,
            "policy_allowed" if self.allowed else "policy_denied",
        )


def test_service_application_admin_can_set_quota_without_django_user():
    principal = Principal.objects.create(kind="service", name="Administrator")
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.manage_quota"})),
        frozenset(),
    )
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    provider = Provider()

    services.admin_set_workspace_quota_policy(
        actor,
        provider,
        workspace.uuid,
        QUOTA_RESOURCE_MEMBER_SEATS,
        3,
        QUOTA_MODE_ENFORCING,
    )

    assert WorkspaceQuotaPolicy.objects.get(workspace=workspace).limit == 3
    assert provider.requests[0].action == "workspace.manage_quota"
    assert provider.requests[0].scope.account_uuid == account.uuid
    assert AuditLog.objects.filter(
        entity_type="workspace", entity_id=workspace.pk, actor_principal_uuid=actor.principal.uuid
    ).exists()


def test_denial_leaves_quota_unchanged():
    principal = Principal.objects.create(kind="service", name="Administrator")
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.manage_quota"})),
        frozenset(),
    )
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)

    with pytest.raises(services.AccountScopeError):
        services.admin_set_workspace_quota_policy(
            actor,
            Provider(allowed=False),
            workspace.uuid,
            QUOTA_RESOURCE_MEMBER_SEATS,
            3,
            QUOTA_MODE_ENFORCING,
        )
    assert not WorkspaceQuotaPolicy.objects.filter(workspace=workspace).exists()


def test_archive_between_policy_check_and_quota_lock_rejects_change():
    principal = Principal.objects.create(kind="service", name="Administrator")
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.manage_quota"})),
        frozenset(),
    )
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)

    class ArchiveDuringCheck(Provider):
        def check(self, request):
            decision = super().check(request)
            Workspace.objects.filter(pk=workspace.pk).update(archived_at=timezone.now())
            return decision

    with pytest.raises(services.WorkspaceQuotaError) as error:
        services.admin_set_workspace_quota_policy(
            actor, ArchiveDuringCheck(), workspace.uuid, QUOTA_RESOURCE_MEMBER_SEATS, 3, QUOTA_MODE_ENFORCING
        )

    assert error.value.code == "quota_workspace_not_found"
    assert not WorkspaceQuotaPolicy.objects.filter(workspace=workspace).exists()


def test_policy_quota_api_preserves_service_principal_attribution(monkeypatch):
    from workspaces.api.account_admin_views import AccountWorkspaceQuotaPolicyView

    principal = Principal.objects.create(kind="service", name="Administrator")
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.manage_quota"})),
        frozenset(),
    )
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().put(
        "/api/v1/accounts/quota/",
        {"resource": QUOTA_RESOURCE_MEMBER_SEATS, "limit": 4, "mode": QUOTA_MODE_ENFORCING},
        format="json",
    )
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = AccountWorkspaceQuotaPolicyView.as_view()(request, workspace_uuid=workspace.uuid)

    assert response.status_code == 200
    assert response.data["limit"] == 4
    assert AuditLog.objects.filter(
        entity_type="workspace", entity_id=workspace.id, actor_principal_uuid=actor.principal.uuid
    ).exists()
