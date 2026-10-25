"""Credential HTTP ownership, one-time delivery and no session fallback."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from shared.authorization import AuthorizationDecision, DecisionKind

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("collection", ["personal", "services"])
@pytest.mark.parametrize(
    "query", [{"offset": -1}, {"offset": 100001}, {"limit": 0}, {"limit": 201}, {"limit": "bad"}, {"unknown": 1}]
)
def test_credential_pagination_rejects_invalid_queries(django_user_model, collection, query):
    user = django_user_model.objects.create_user(username="page-reader")
    client = APIClient()
    client.force_login(user, backend="config.auth.PlatformModelBackend")
    assert client.get(f"/api/v1/credentials/{collection}/", query).status_code == 400


def test_django_admin_cannot_bypass_credential_issuance_policy(admin_client):
    response = admin_client.post(
        "/admin/shared/apitoken/add/",
        {
            "name": "Bypass attempt",
            "scopes": '["ctf:event:read"]',
            "expires_at_0": "",
            "expires_at_1": "",
        },
    )
    assert response.status_code == 403


def test_personal_api_delivers_once_and_preserves_own_revoke_after_grant_loss(django_user_model, monkeypatch):
    from shared.authorization import port

    user = django_user_model.objects.create_user(username="api-token-owner")
    client = APIClient()
    client.force_login(user, backend="config.auth.PlatformModelBackend")
    allowed = True
    provider = SimpleNamespace(
        check=lambda request: AuthorizationDecision(
            DecisionKind.ALLOWED if allowed else DecisionKind.DENIED,
            "policy_allowed" if allowed else "policy_denied",
        )
    )
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    response = client.post(
        "/api/v1/credentials/personal/",
        {
            "name": "Read audit",
            "scopes": ["authorization:installation.read_audit"],
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            "target_type": "installation",
        },
        format="json",
    )
    assert response.status_code == 201
    raw = response.json()["token"]
    identity = response.json()["credential_uuid"]
    assert response["Cache-Control"] == "no-store"
    listing = client.get("/api/v1/credentials/personal/")
    assert listing.status_code == 200
    assert raw not in listing.content.decode()
    allowed = False
    revoke = client.post(f"/api/v1/credentials/personal/{identity}/revoke/", {}, format="json")
    assert revoke.status_code == 204
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
    assert client.get("/api/v1/credentials/personal/").status_code == 401


def test_service_administration_creates_no_human_or_implicit_grant(django_user_model, monkeypatch, settings):
    from management.models import Principal
    from shared.authorization import port

    settings.GCP_SERVICE_TOKEN_AUDIENCE = "https://portal.example.test"
    user = django_user_model.objects.create_user(username="service-administrator")
    client = APIClient()
    client.force_login(user, backend="config.auth.PlatformModelBackend")
    provider = SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed"))
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    response = client.post(
        "/api/v1/credentials/services/",
        {
            "name": "Agent",
            "subject": "123456789012345678901",
            "scopes": ["authorization:installation.read_audit"],
        },
        format="json",
    )
    assert response.status_code == 201
    service = Principal.objects.get(uuid=response.json()["principal_uuid"])
    assert service.kind == "service"
    assert service.user_id is None
    assert django_user_model.objects.count() == 1
    service.responsible_user = user
    service.save(update_fields=["responsible_user", "updated_at"])
    update_url = f"/api/v1/credentials/services/principals/{service.uuid}/"
    assert client.post(update_url, {"is_active": False}, format="json").status_code == 204
    service.refresh_from_db()
    assert service.responsible_user_id == user.pk
    assert not service.is_active
    assert client.post(update_url, {"is_active": True, "responsible_user_id": None}, format="json").status_code == 204
    service.refresh_from_db()
    assert service.responsible_user_id is None
    assert service.is_active
    listing = client.get("/api/v1/credentials/services/").json()["results"][0]
    assert listing["principal_active"] and listing["admission_active"]
