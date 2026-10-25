"""Policy-aware workspace egress administration for S8."""

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
from workspaces.models import Workspace

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def check(self, request):
        return AuthorizationDecision(
            DecisionKind.ALLOWED if self.allowed else DecisionKind.DENIED,
            "policy_allowed" if self.allowed else "policy_denied",
        )


def _actor():
    principal = Principal.objects.create(kind="service", name="Administrator")
    return CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.manage_egress"})),
        frozenset(),
    )


def test_service_admin_sets_egress_with_strict_principal_audit():
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    actor = _actor()

    result = services.admin_set_workspace_egress_policy(actor, Provider(), workspace.uuid, "none")

    workspace.refresh_from_db()
    assert workspace.egress_policy == "none"
    assert result.egress_policy == "none"
    assert AuditLog.objects.filter(
        entity_type="workspace", entity_id=workspace.id, actor_principal_uuid=actor.principal.uuid
    ).exists()


def test_denial_and_archived_target_cannot_change_egress():
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    actor = _actor()

    with pytest.raises(services.AccountScopeError):
        services.admin_set_workspace_egress_policy(actor, Provider(allowed=False), workspace.uuid, "none")
    workspace.archived_at = timezone.now()
    workspace.save(update_fields=["archived_at"])
    with pytest.raises(services.AccountScopeError):
        services.admin_set_workspace_egress_policy(actor, Provider(), workspace.uuid, "none")
    workspace.refresh_from_db()
    assert workspace.egress_policy != "none"


def test_service_admin_egress_api_uses_policy_and_principal_audit(monkeypatch):
    from workspaces.api.account_admin_views import AccountWorkspaceEgressPolicyView

    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    actor = _actor()
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().put("/api/v1/accounts/egress/", {"egress_policy": "none"}, format="json")
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = AccountWorkspaceEgressPolicyView.as_view()(request, workspace_uuid=workspace.uuid)

    assert response.status_code == 200
    assert response.data["egress_policy"] == "none"
    assert AuditLog.objects.filter(
        entity_type="workspace", entity_id=workspace.id, actor_principal_uuid=actor.principal.uuid
    ).exists()
