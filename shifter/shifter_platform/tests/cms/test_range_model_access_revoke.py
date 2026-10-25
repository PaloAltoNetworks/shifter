"""Range model-access revoke API — authority, parity, error mapping (M09, #2126).

The deep grant-fencing behavior is covered by the engine lifecycle tests; here
the service is stubbed to drive the DRF boundary: session/CSRF + scoped-token
parity, workspace-authority denial, and unavailable-range mapping.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import MODEL_ACCESS_RANGE_READ, MODEL_ACCESS_RANGE_WRITE
from shared.model_access import ContractError
from workspaces.services import WorkspaceAuthorizationError

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("personal_token_use_grant")]

User = get_user_model()


@pytest.fixture
def admin():
    return User.objects.create_user(username="range-admin", email="ra@example.com", password="pw")


def _url() -> str:
    return f"/api/v1/cms/ranges/{uuid4()}/model-sources/revoke/"


def _session(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _token(user, *scopes) -> APIClient:
    _, raw = ApiToken.create_token(name="m9", created_by=user, scopes=list(scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def test_unauthenticated_is_rejected():
    assert APIClient().post(_url(), {}, format="json").status_code == 401


def test_success_returns_range_status(admin, monkeypatch):
    status_payload = {"request_id": str(uuid4()), "revision": 3, "runtime": {"state": "unavailable", "assignments": []}}
    monkeypatch.setattr("cms.api.range_model_sources.revoke_range_model_sources", lambda *a, **k: status_payload)
    response = _session(admin).post(_url(), {}, format="json")
    assert response.status_code == 200
    assert response.json()["runtime"]["state"] == "unavailable"


def test_workspace_authority_denied_is_403(admin, monkeypatch):
    def _raise(*a, **k):
        raise WorkspaceAuthorizationError("Range access denied")

    monkeypatch.setattr("cms.api.range_model_sources.revoke_range_model_sources", _raise)
    assert _session(admin).post(_url(), {}, format="json").status_code == 403


def test_unavailable_range_is_403(admin, monkeypatch):
    def _raise(*a, **k):
        raise ContractError("source.range_unavailable")

    monkeypatch.setattr("cms.api.range_model_sources.revoke_range_model_sources", _raise)
    assert _session(admin).post(_url(), {}, format="json").status_code == 403


def test_scoped_token_parity(admin, monkeypatch):
    monkeypatch.setattr("cms.api.range_model_sources.revoke_range_model_sources", lambda *a, **k: {"ok": True})
    assert _token(admin, MODEL_ACCESS_RANGE_READ).post(_url(), {}, format="json").status_code == 403
    assert _token(admin, MODEL_ACCESS_RANGE_WRITE).post(_url(), {}, format="json").status_code == 200
