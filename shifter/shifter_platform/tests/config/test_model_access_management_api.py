"""Scoped model-access sharing/catalog management API (M09, #2126 / PLAT-202).

Boundary behavior: authentication, session/CSRF + scoped-token parity, and the
bounded owner-domain error mapping. Deep sharing logic is covered by the Engine
and composition-root service tests; here the services are stubbed so the tests
drive the DRF boundary itself.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from cms.services import EngineSharingError
from config.model_access_sharing import ModelAccessCompositionError
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import CTF_EVENT_READ, MODEL_ACCESS_SHARING_READ

pytestmark = pytest.mark.django_db

User = get_user_model()

VALIDATE = "/api/v1/model-access/bindings/validate/"
SELECTOR = "/api/v1/model-access/bindings/selector-preview/"
POLICY = "/api/v1/model-access/bindings/policy-preview/"
PUBLISH = "/api/v1/model-access/bindings/publish/"
DRAIN = "/api/v1/model-access/bindings/drain/"


@pytest.fixture
def planner():
    return User.objects.create_user(username="planner", email="planner@example.com", password="pw")


@pytest.fixture
def available(monkeypatch):
    """Model access is configured; catalog + deployment id resolve server-side."""
    monkeypatch.setattr("config.api_model_access._current_envelope", lambda: (object(), uuid.uuid4()))


@pytest.fixture
def draft_ok(monkeypatch):
    """Skip closed-contract construction; the service call is what is under test."""
    monkeypatch.setattr("config.api_model_access._binding_and_pool", lambda data, deployment_id: (object(), object()))


def _session(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _token(user, *scopes) -> APIClient:
    _, raw = ApiToken.create_token(name="m9", created_by=user, scopes=list(scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


@pytest.mark.usefixtures("personal_token_use_grant")
class TestAuthenticationAndScopeParity:
    def test_unauthenticated_is_rejected(self):
        # 401: the bearer auth scheme supplies a WWW-Authenticate header.
        assert APIClient().post(VALIDATE, {"binding": {}, "pool": {}}, format="json").status_code == 401

    def test_token_without_model_access_scope_is_rejected(self, planner, available, draft_ok, monkeypatch):
        monkeypatch.setattr("cms.services.engine_validate_sharing_binding", lambda **_: None)
        client = _token(planner, CTF_EVENT_READ)
        assert client.post(VALIDATE, {"binding": {}, "pool": {}}, format="json").status_code == 403

    def test_token_with_sharing_read_scope_reaches_service(self, planner, available, draft_ok, monkeypatch):
        monkeypatch.setattr("cms.services.engine_validate_sharing_binding", lambda **_: None)
        client = _token(planner, MODEL_ACCESS_SHARING_READ)
        response = client.post(VALIDATE, {"binding": {}, "pool": {}}, format="json")
        assert response.status_code == 200
        assert response.json() == {"valid": True}

    def test_publish_token_needs_write_scope_not_read(self, planner, available, draft_ok, monkeypatch):
        monkeypatch.setattr("config.model_access_sharing.publish_model_access_binding", lambda **_: None)
        read_only = _token(planner, MODEL_ACCESS_SHARING_READ)
        body = {"binding": {}, "pool": {}, "expected_definition_revision": 0}
        assert read_only.post(PUBLISH, body, format="json").status_code == 403


class TestSessionParityAndAvailability:
    def test_session_validate_reaches_service(self, planner, available, draft_ok, monkeypatch):
        monkeypatch.setattr("cms.services.engine_validate_sharing_binding", lambda **_: None)
        response = _session(planner).post(VALIDATE, {"binding": {}, "pool": {}}, format="json")
        assert response.status_code == 200

    def test_unconfigured_deployment_reports_unavailable(self, planner, monkeypatch):
        monkeypatch.setattr("config.api_model_access._current_envelope", lambda: None)
        response = _session(planner).post(VALIDATE, {"binding": {}, "pool": {}}, format="json")
        assert response.status_code == 503


class TestErrorMapping:
    def _publish_body(self):
        return {"binding": {}, "pool": {}, "expected_definition_revision": 3}

    def test_revision_conflict_is_409(self, planner, available, draft_ok, monkeypatch):
        def _raise(**_):
            raise EngineSharingError("sharing.revision_conflict")

        monkeypatch.setattr("config.model_access_sharing.publish_model_access_binding", _raise)
        response = _session(planner).post(PUBLISH, self._publish_body(), format="json")
        assert response.status_code == 409

    def test_composition_denied_is_403(self, planner, available, draft_ok, monkeypatch):
        def _raise(**_):
            raise ModelAccessCompositionError("denied")

        monkeypatch.setattr("config.model_access_sharing.publish_model_access_binding", _raise)
        response = _session(planner).post(PUBLISH, self._publish_body(), format="json")
        assert response.status_code == 403

    def test_drain_binding_not_found_is_404(self, planner, available, monkeypatch):
        def _raise(**_):
            raise EngineSharingError("sharing.binding_not_found")

        monkeypatch.setattr("config.model_access_sharing.drain_model_access_binding", _raise)
        body = {"sharing_binding_id": "b1", "expected_definition_revision": 1}
        response = _session(planner).post(DRAIN, body, format="json")
        assert response.status_code == 404

    def test_publish_success_returns_revision(self, planner, available, draft_ok, monkeypatch):
        # The composition wrapper returns a bounded revision projection dict.
        revision = {"sharing_binding_id": "b1", "definition_revision": 4, "state": "active"}
        monkeypatch.setattr("config.model_access_sharing.publish_model_access_binding", lambda **_: revision)
        response = _session(planner).post(PUBLISH, self._publish_body(), format="json")
        assert response.status_code == 201
        assert response.json() == revision


class TestDraftSealing:
    def test_injects_server_deployment_and_placeholder_publisher(self):
        from config.api_model_access import _binding_and_pool

        deployment_id = uuid.uuid4()
        draft = {
            "binding": {
                "sharing_binding_id": "b1",
                # A client-supplied deployment id must not survive: the server owns it.
                "deployment_id": str(uuid.uuid4()),
                "selector": {"kind": "all_ranges"},
                "membership_mode": "dynamic",
                "profile_id": "coding",
                "sharing_pool_id": "pool-a",
                "facets": ["profile", "spend"],
                "priority": 0,
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_until": "2027-01-01T00:00:00Z",
            },
            "pool": {"sharing_pool_id": "pool-a", "routing_revision": 1, "spend_account_refs": ["acct-1"]},
        }
        binding, pool = _binding_and_pool(draft, deployment_id)
        assert str(binding.deployment_id) == str(deployment_id)
        # The client cannot forge the publisher; publish re-seals it server-side.
        assert binding.authorized_publisher_ref.reference == "draft:unresolved"
        assert pool.sharing_pool_id == "pool-a"


@pytest.mark.usefixtures("personal_token_use_grant")
class TestEffectivePolicyPreviewAuthority:
    """Effective-policy preview is operator-only — it must not become a cross-tenant read."""

    def _subject(self):
        return {"subject": {"owner": "deployment", "reference": "range:x"}}

    def test_non_operator_is_denied(self, planner, available):
        assert _session(planner).post(POLICY, self._subject(), format="json").status_code == 403

    def test_operator_reaches_service(self, available, monkeypatch):
        operator = User.objects.create_superuser(username="op", email="op@example.com", password="pw")
        monkeypatch.setattr("cms.services.engine_preview_effective_policy", lambda **_: object())
        monkeypatch.setattr("config.api_model_access._project_policy", lambda policy: {"stale": False})
        response = _session(operator).post(POLICY, self._subject(), format="json")
        assert response.status_code == 200

    def test_non_operator_token_with_operator_scope_still_denied(self, planner, available):
        # A scope is never operator authority: a token with the operator scope but a
        # non-superuser owner is still refused.
        client = _token(planner, "model-access:operator:read")
        assert client.post(POLICY, self._subject(), format="json").status_code == 403


class TestGeneratedContract:
    def test_openapi_publishes_exact_model_access_scopes(self):
        import json
        import pathlib

        spec = json.loads((pathlib.Path(__file__).resolve().parents[2] / "openapi" / "v1.json").read_text())
        expected = {
            "/api/v1/model-access/bindings/validate/": ("post", "model-access:sharing:read"),
            "/api/v1/model-access/bindings/publish/": ("post", "model-access:sharing:write"),
            "/api/v1/model-access/bindings/drain/": ("post", "model-access:sharing:write"),
            "/api/v1/model-access/bindings/policy-preview/": ("post", "model-access:operator:read"),
            "/api/v1/cms/ranges/{request_id}/model-sources/revoke/": ("post", "model-access:range:write"),
            "/api/v1/ctf/events/{event_id}/model-access/assessment/": ("get", "model-access:event:read"),
            "/api/v1/ctf/me/model-access/": ("get", "model-access:participant:read"),
        }
        for path, (method, scope) in expected.items():
            operation = spec["paths"][path][method]
            assert operation["x-required-scopes"] == [scope], path


class TestSelectorPreview:
    def test_selector_preview_returns_matched_count(self, planner, monkeypatch):
        resolution = type(
            "Res",
            (),
            {
                "assessment_count": 2,
                "member_refs": (
                    type("R", (), {"owner": "deployment", "reference": "range:a"})(),
                    type("R", (), {"owner": "deployment", "reference": "range:b"})(),
                ),
            },
        )()
        monkeypatch.setattr("config.model_access_sharing.resolve_model_access_selector", lambda *_: resolution)
        response = _session(planner).post(SELECTOR, {"selector": {"kind": "all_ranges"}}, format="json")
        assert response.status_code == 200
        assert response.json()["matched"] == 2
