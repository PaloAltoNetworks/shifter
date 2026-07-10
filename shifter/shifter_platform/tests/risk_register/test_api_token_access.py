"""End-to-end DRF tests: platform API tokens against the risk-register API.

PLAT-102 proves the token + scope path end-to-end on the surface that is
already DRF. Fills a real gap: there was no HTTP-level DRF auth test before.
"""

from __future__ import annotations

import hashlib

import pytest
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient

from risk_register.api.views import CommentViewSet, RiskViewSet
from risk_register.models import APIKey
from shared.api_tokens import scopes
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken

from .conftest import grant_risk_register_access

pytestmark = pytest.mark.django_db

RISKS_URL = "/api/v1/risks/"
API_KEYS_URL = "/api/v1/api-keys/"


@pytest.fixture
def staff(django_user_model):
    user = django_user_model.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="pw",
        is_staff=True,
    )
    grant_risk_register_access(user)
    return user


@pytest.fixture
def client():
    return APIClient()


def _bearer(client, raw):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestTokenReadAccess:
    def test_read_token_can_list(self, client, staff):
        _, raw = ApiToken.create_token(name="r", created_by=staff, scopes=[scopes.RISK_READ])
        resp = _bearer(client, raw).get(RISKS_URL)
        assert resp.status_code == 200

    def test_unauthenticated_is_401(self, client):
        assert client.get(RISKS_URL).status_code == 401

    def test_token_without_risk_scope_is_403(self, client, staff):
        _, raw = ApiToken.create_token(name="wrong", created_by=staff, scopes=[scopes.MISSION_CONTROL_RANGE_READ])
        assert _bearer(client, raw).get(RISKS_URL).status_code == 403

    def test_revoked_token_is_401(self, client, staff):
        token, raw = ApiToken.create_token(name="r", created_by=staff, scopes=[scopes.RISK_READ])
        token.revoke()
        assert _bearer(client, raw).get(RISKS_URL).status_code == 401

    def test_risk_register_auth_is_token_and_session_only(self):
        # PLAT-106 / #1124: the legacy risk_register APIKeyAuthentication is
        # retired; the surface authenticates only via platform ApiToken + session.
        expected = [ApiTokenAuthentication, SessionAuthentication]
        assert RiskViewSet.authentication_classes == expected
        assert CommentViewSet.authentication_classes == expected


class TestTokenWriteAccess:
    def test_read_token_cannot_create(self, client, staff):
        _, raw = ApiToken.create_token(name="r", created_by=staff, scopes=[scopes.RISK_READ])
        resp = _bearer(client, raw).post(RISKS_URL, {"title": "T", "description": "D"}, format="json")
        assert resp.status_code == 403

    def test_write_token_can_create(self, client, staff):
        _, raw = ApiToken.create_token(name="w", created_by=staff, scopes=[scopes.RISK_WRITE])
        resp = _bearer(client, raw).post(RISKS_URL, {"title": "T", "description": "D"}, format="json")
        assert resp.status_code == 201

    def test_write_token_create_is_audited_with_token_actor(self, client, staff):
        from risk_register.models import AuditLog

        token, raw = ApiToken.create_token(name="w", created_by=staff, scopes=[scopes.RISK_WRITE])
        _bearer(client, raw).post(RISKS_URL, {"title": "T", "description": "D"}, format="json")
        row = AuditLog.objects.filter(entity_type=AuditLog.EntityType.RISK, action=AuditLog.Action.CREATE).latest(
            "timestamp"
        )
        assert row.actor_type == AuditLog.ActorType.APIKEY
        assert row.actor_id == token.id


class TestSessionStillWorks:
    def test_staff_session_can_list(self, client, staff):
        client.force_authenticate(user=staff)
        assert client.get(RISKS_URL).status_code == 200


class TestApiKeysEndpointRetired:
    def test_api_keys_endpoint_is_gone(self, client, staff):
        # The legacy /api/v1/api-keys/ management endpoint was retired with the
        # risk_register APIKey (PLAT-106 / #1124); it no longer routes.
        _, raw = ApiToken.create_token(name="w", created_by=staff, scopes=[scopes.RISK_WRITE])
        assert _bearer(client, raw).get(API_KEYS_URL).status_code == 404


class TestLegacyApiKeyHeaderInert:
    def test_x_api_key_header_does_not_authenticate(self, client, staff):
        # An archival rr_live_ key must not authenticate: no authenticator reads
        # X-API-Key anymore, so the request is unauthenticated (401), not merely
        # forbidden (403).
        raw = "rr_live_" + "z" * 32
        APIKey.objects.create(
            name="archival",
            prefix=raw[:8],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            created_by=staff,
        )
        client.credentials(HTTP_X_API_KEY=raw)
        assert client.get(RISKS_URL).status_code == 401


class TestRiskRegisterErrorEnvelope:
    def test_manual_restore_error_uses_platform_api_envelope(self, client, staff):
        from risk_register.models import Risk

        risk = Risk.objects.create(title="T", description="D")
        client.force_authenticate(user=staff)

        resp = client.post(f"{RISKS_URL}{risk.pk}/restore/")

        assert resp.status_code == 400
        payload = resp.json()
        assert payload["error"]["code"] == "bad_request"
        assert payload["error"]["message"] == "Risk is not deleted"
        assert payload["error"]["request_id"]
