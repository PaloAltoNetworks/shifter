"""Global audit reads require installation policy for direct service callers."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from management.models import Principal
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.authorization import (
    AuthorizationDecision,
    AuthorizationProviderBindingError,
    CredentialCeiling,
    DecisionKind,
)
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, decision=DecisionKind.ALLOWED):
        self.decision = decision
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        reason = "policy_allowed" if self.decision == DecisionKind.ALLOWED else "policy_denied"
        return AuthorizationDecision(self.decision, reason)


def _actor(kind, actions):
    if kind == "human":
        user = get_user_model().objects.create_user(username=f"audit-{uuid4()}")
        principal = Principal.objects.get(user=user)
    else:
        principal = Principal.objects.create(kind="service", name="Audit service")
    ref = PrincipalRef(principal.uuid, kind)
    return CredentialContext(
        ref, "session" if kind == "human" else "service", uuid4(), CredentialCeiling(actions), frozenset()
    )


@pytest.mark.parametrize("kind", ["human", "service"])
def test_full_application_auditor_can_read_global_ledger(kind):
    from shared.audit import authorized_audit_events

    actor = _actor(kind, frozenset({"installation.read_audit"}))
    audit_log(AuditEvent(entity_type=AuditEntityType.CONFIG, entity_id=1, action=AuditAction.UPDATE), strict=True)
    provider = Provider()

    rows = authorized_audit_events(actor, provider)

    assert rows.filter(entity_type=AuditEntityType.CONFIG, entity_id=1).exists()
    assert provider.requests[0].action == "installation.read_audit"
    assert provider.requests[0].scope.kind == "installation"


def test_customer_permission_ceiling_and_provider_denial_cannot_read_global_ledger():
    from shared.audit import AuditReadDenied, authorized_audit_events

    with pytest.raises(AuditReadDenied):
        authorized_audit_events(_actor("human", frozenset({"account.read"})), Provider())
    with pytest.raises(AuditReadDenied):
        authorized_audit_events(
            _actor("service", frozenset({"installation.read_audit"})), Provider(DecisionKind.DENIED)
        )


@pytest.mark.parametrize("kind", ["human", "service"])
def test_policy_audit_api_admits_full_application_admin_without_staff_flag(monkeypatch, kind):
    from shared.api.audit import PolicyAuditLogViewSet

    actor = _actor(kind, frozenset({"installation.read_audit"}))
    provider = Provider()
    monkeypatch.setattr("shared.api.audit.configured_authorization_provider", lambda: provider)
    request = APIRequestFactory().get("/api/v1/audit/")
    if kind == "human":
        user = get_user_model().objects.get(identity_principal__uuid=actor.principal.uuid)
        force_authenticate(request, user=user)
    else:
        request.credential_context = actor
        force_authenticate(request, token=actor)

    response = PolicyAuditLogViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 200
    assert provider.requests[0].action == "installation.read_audit"


def test_policy_audit_api_denies_customer_only_service_credential(monkeypatch):
    from shared.api.audit import PolicyAuditLogViewSet

    actor = _actor("service", frozenset({"account.read"}))
    monkeypatch.setattr("shared.api.audit.configured_authorization_provider", lambda: Provider())
    request = APIRequestFactory().get("/api/v1/audit/")
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = PolicyAuditLogViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 403
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_DENIED, actor_principal_uuid=actor.principal.uuid).exists()


def test_policy_audit_api_reports_provider_unavailability_without_exposing_detail(monkeypatch):
    from shared.api.audit import PolicyAuditLogViewSet

    actor = _actor("service", frozenset({"installation.read_audit"}))

    def unavailable():
        raise AuthorizationProviderBindingError("private provider detail")

    monkeypatch.setattr("shared.api.audit.configured_authorization_provider", unavailable)
    request = APIRequestFactory().get("/api/v1/audit/")
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = PolicyAuditLogViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 503
    assert "private provider detail" not in str(response.data)
