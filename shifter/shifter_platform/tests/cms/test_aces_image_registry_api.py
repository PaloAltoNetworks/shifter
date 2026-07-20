"""DRF boundary coverage for the tenant ACES image registry API (#1566).

Drives the real ``/api/v1/cms/aces-image-mappings/`` endpoints against a real
database and the real ``engine.services`` write path: register/upsert, list with
the allowlisted projection, soft-disable, CMS-authoring authz, and the
``SHIFTER_ACES_NATIVE_PROVISIONING`` gate (every endpoint 404s with the flag off).
"""

from __future__ import annotations

import importlib

import pytest
from django.contrib.auth.models import Group
from django.urls import clear_url_caches
from rest_framework.test import APIClient

from engine.models import AcesImageMapping
from engine.services import AcesImageMappingOptions, upsert_aces_image_mapping
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = pytest.mark.django_db

LIST_CREATE_URL = "/api/v1/cms/aces-image-mappings/"
DISABLE_URL = "/api/v1/cms/aces-image-mappings/disable/"

_VIEW_FIELDS = {
    "id",
    "provider",
    "source_name",
    "source_version",
    "image_ref",
    "machine_type",
    "disk_size_gb",
    "disk_type",
    "enabled",
    "notes",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _restore_urlconf() -> None:
    yield
    _reload_urlconfs()


def _reload_urlconfs() -> None:
    import cms.api.urls
    import config.api_urls
    import config.urls

    clear_url_caches()
    importlib.reload(cms.api.urls)
    importlib.reload(config.api_urls)
    importlib.reload(config.urls)
    clear_url_caches()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="aces-img-staff@example.com",
        email="aces-img-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def threat_research_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="aces-img-threat@example.com",
        email="aces-img-threat@example.com",
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


def _token(user, *granted: str) -> str:
    _, raw = ApiToken.create_token(name="aces-img", created_by=user, scopes=list(granted))
    return raw


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestRegister:
    @pytest.fixture(autouse=True)
    def _native_on(self, settings):
        settings.ACES_NATIVE_PROVISIONING_ENABLED = True

    def test_register_creates_mapping(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {
                "provider": "gce",
                "source_name": "alpine",
                "image_ref": "projects/x/global/images/alpine-3-19",
                "source_version": "3.19",
                "disk_size_gb": 20,
            },
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "gce"
        assert body["source_name"] == "alpine"
        assert body["enabled"] is True
        assert set(body) == _VIEW_FIELDS
        assert AcesImageMapping.objects.count() == 1

    def test_register_is_idempotent_upsert(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        payload = {"provider": "gce", "source_name": "kali", "image_ref": "img-a"}
        api_client.post(LIST_CREATE_URL, payload, format="json")
        response = api_client.post(LIST_CREATE_URL, {**payload, "image_ref": "img-b"}, format="json")
        assert response.status_code == 200
        assert response.json()["image_ref"] == "img-b"
        assert AcesImageMapping.objects.count() == 1

    def test_invalid_provider_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "azure", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_missing_required_field_is_shape_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(LIST_CREATE_URL, {"provider": "gce"}, format="json")
        assert response.status_code == 400

    def test_non_positive_disk_size_is_shape_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img", "disk_size_gb": 0},
            format="json",
        )
        assert response.status_code == 400

    def test_write_token_can_register(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)
        response = _bearer(api_client, raw).post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 200

    def test_read_only_token_cannot_register(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 403


class TestList:
    @pytest.fixture(autouse=True)
    def _native_on(self, settings):
        settings.ACES_NATIVE_PROVISIONING_ENABLED = True

    def test_lists_rows_with_allowlisted_fields(self, api_client, threat_research_user):
        upsert_aces_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.get(LIST_CREATE_URL)
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert set(results[0]) == _VIEW_FIELDS

    def test_include_disabled_false_filters_disabled(self, api_client, threat_research_user):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_aces_image_mapping(
            provider="gce",
            source_name="ubuntu",
            image_ref="img",
            options=AcesImageMappingOptions(enabled=False),
        )
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.get(LIST_CREATE_URL, {"include_disabled": "false"})
        assert [r["source_name"] for r in response.json()] == ["kali"]

    def test_read_token_can_list(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).get(LIST_CREATE_URL)
        assert response.status_code == 200

    def test_wrong_scope_forbidden(self, api_client, staff_user):
        raw = _token(staff_user, scopes.RISK_READ)  # valid token, wrong scope
        response = _bearer(api_client, raw).get(LIST_CREATE_URL)
        assert response.status_code == 403


class TestDisable:
    @pytest.fixture(autouse=True)
    def _native_on(self, settings):
        settings.ACES_NATIVE_PROVISIONING_ENABLED = True

    def test_disable_sets_enabled_false_preserving_image_ref(self, api_client, threat_research_user):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-keep")
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "kali"}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["image_ref"] == "img-keep"
        assert AcesImageMapping.objects.get(source_name="kali").enabled is False

    def test_disable_missing_mapping_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "absent"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_read_only_token_cannot_disable(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).post(
            DISABLE_URL,
            {"provider": "gce", "source_name": "kali"},
            format="json",
        )
        assert response.status_code == 403


class TestNativeProvisioningGate:
    """With SHIFTER_ACES_NATIVE_PROVISIONING off, the surface is inert (404)."""

    @pytest.fixture(autouse=True)
    def _native_off(self, settings):
        settings.ACES_NATIVE_PROVISIONING_ENABLED = False

    def test_list_is_404_when_flag_off(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.get(LIST_CREATE_URL)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_register_is_404_when_flag_off(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 404
        assert AcesImageMapping.objects.count() == 0

    def test_disable_is_404_when_flag_off(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "kali"}, format="json")
        assert response.status_code == 404
