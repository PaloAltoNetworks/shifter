"""DRF boundary for the uniform pack-registration endpoint (#1578, ADR-034).

POST /api/v1/cms/catalog/packs/ is the authenticated operator entrypoint onto the
single ``register_pack`` service. It requires the CMS authoring WRITE scope,
validates the incoming pack, and returns the shared error envelope on failure.
"""

from __future__ import annotations

import importlib
from contextlib import suppress
from pathlib import Path

import pytest
from django.urls import clear_url_caches
from rest_framework.test import APIClient

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import PackDigestError, pack_digest
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

PACKS_URL = "/api/v1/cms/catalog/packs/"


def _reload_urlconfs() -> None:
    import cms.api.urls
    import config.api_urls
    import config.urls

    clear_url_caches()
    importlib.reload(cms.api.urls)
    importlib.reload(config.api_urls)
    importlib.reload(config.urls)
    clear_url_caches()


@pytest.fixture(autouse=True)
def _restore_urlconf():
    yield
    _reload_urlconfs()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="pack-api-staff@example.com",
        email="pack-api-staff@example.com",
        is_staff=True,
    )


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="pack-api", created_by=user, scopes=list(granted_scopes))
    return raw


# A repo pack's catalog id is bound to its validated identity, so the fixture's
# scenario_id must equal the pack name.
API_FIXTURE_NAME = "api-fixture"


@pytest.fixture
def repo_pack(make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    make_pack(tmp_path / "packs" / API_FIXTURE_NAME, name=API_FIXTURE_NAME)
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    return f"packs/{API_FIXTURE_NAME}"


def _body(package_ref: str, **overrides) -> dict:
    body = {
        "scenario_id": API_FIXTURE_NAME,
        "source_kind": "repo",
        "contract_kind": "raes",
        "contract_profile": "shifter",
        "package_ref": package_ref,
        "package_version": "0.1.0",
        "package_digest": "sha256:" + "a" * 64,
        "provenance": {"repo": "acme/example"},
    }
    body.update(overrides)
    if "package_digest" not in overrides and body["source_kind"] == "repo":
        from django.conf import settings

        with suppress(PackDigestError, OSError):
            body["package_digest"] = pack_digest(Path(settings.RAES_PACKAGE_ROOT) / package_ref)
    return body


class TestPackRegisterEndpoint:
    def test_write_scope_registers_pack(self, api_client, staff_user, repo_pack):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)
        response = _bearer(api_client, raw).post(
            PACKS_URL,
            _body(repo_pack),
            format="json",
            HTTP_X_REQUEST_ID="pack-api-correlation",
        )
        assert response.status_code == 201, response.data
        assert response.data["scenario_id"] == API_FIXTURE_NAME
        assert RaesPackageSource.objects.filter(scenario_id=API_FIXTURE_NAME).exists()
        assert AuditLog.objects.filter(
            request_id="pack-api-correlation",
            entity_type=AuditEntityType.SCENARIO,
            action=AuditAction.CREATE,
        ).exists()

    def test_read_scope_is_forbidden(self, api_client, staff_user, repo_pack):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).post(PACKS_URL, _body(repo_pack), format="json")
        assert response.status_code == 403
        assert not RaesPackageSource.objects.filter(scenario_id=API_FIXTURE_NAME).exists()

    def test_unauthenticated_is_rejected(self, api_client, repo_pack):
        response = api_client.post(PACKS_URL, _body(repo_pack), format="json")
        assert response.status_code in (401, 403)

    def test_missing_field_returns_400(self, api_client, staff_user, repo_pack):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)
        body = _body(repo_pack)
        del body["package_digest"]
        response = _bearer(api_client, raw).post(PACKS_URL, body, format="json")
        assert response.status_code == 400
        assert "error" in response.data

    def test_duplicate_returns_error_envelope(self, api_client, staff_user, repo_pack):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)
        first = _bearer(api_client, raw).post(PACKS_URL, _body(repo_pack), format="json")
        assert first.status_code == 201
        second = _bearer(api_client, raw).post(PACKS_URL, _body(repo_pack), format="json")
        assert second.status_code in (400, 409)
        assert "error" in second.data
