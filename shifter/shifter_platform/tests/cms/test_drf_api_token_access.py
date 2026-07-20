"""DRF boundary coverage for the canonical CMS API (PLAT-106 / #1122)."""

from __future__ import annotations

import importlib

import pytest
from django.contrib.auth.models import Group
from django.urls import Resolver404, clear_url_caches, resolve
from rest_framework.test import APIClient

from cms.models import Scenario
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = pytest.mark.django_db

YAML_VALIDATE_URL = "/api/v1/cms/scenario-editor/validate-yaml/"
YAML_CREATE_URL = "/api/v1/cms/scenario-editor/scenarios/from-yaml/"
VALID_SCENARIO_YAML = """id: api-created
name: API Created
description: Created through the API
instances:
  - name: Attacker
    role: attacker
    os_type: kali
"""


@pytest.fixture(autouse=True)
def _restore_urlconf() -> None:
    yield
    _reload_urlconfs()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="cms-api-staff@example.com",
        email="cms-api-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def threat_research_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="cms-api-threat@example.com",
        email="cms-api-threat@example.com",
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def regular_user(django_user_model):
    return django_user_model.objects.create_user(
        username="cms-api-regular@example.com",
        email="cms-api-regular@example.com",
    )


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="cms-api", created_by=user, scopes=list(granted_scopes))
    return raw


def _reload_urlconfs() -> None:
    import cms.api.urls
    import config.api_urls
    import config.urls

    clear_url_caches()
    importlib.reload(cms.api.urls)
    importlib.reload(config.api_urls)
    importlib.reload(config.urls)
    clear_url_caches()


class TestCMSAuthoringReadAccess:
    def test_legacy_experiment_api_routes_are_absent(self) -> None:
        _reload_urlconfs()

        with pytest.raises(Resolver404):
            resolve("/api/v1/cms/experiments/scenarios/basic/instances/")


class TestCMSScenarioEditorAPI:
    def test_openapi_schema_includes_scenario_editor_cms_route(self, api_client: APIClient, staff_user) -> None:
        api_client.force_authenticate(user=staff_user)

        response = api_client.get("/api/v1/schema/")

        assert response.status_code == 200
        assert "/api/v1/cms/scenario-editor/validate-yaml/" in response.content.decode()

    def test_session_user_can_validate_yaml(self, api_client: APIClient, threat_research_user) -> None:
        api_client.force_authenticate(user=threat_research_user)

        response = api_client.post(YAML_VALIDATE_URL, {"yaml_content": VALID_SCENARIO_YAML}, format="json")

        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is True
        assert payload["errors"] == []
        assert payload["definition"]["id"] == "api-created"

    def test_read_token_can_validate_yaml(self, api_client: APIClient, staff_user) -> None:
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).post(
            YAML_VALIDATE_URL,
            {"yaml_content": "name: Missing required fields"},
            format="json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False
        assert "Missing required field: id" in payload["errors"]
        assert payload["definition"] is None

    def test_malformed_bearer_fails_closed_over_logged_in_session(self, api_client: APIClient, staff_user) -> None:
        api_client.force_login(staff_user)
        api_client.credentials(HTTP_AUTHORIZATION="Bearer shf_missing.invalid")

        response = api_client.post(YAML_VALIDATE_URL, {"yaml_content": "name: X"}, format="json")

        assert response.status_code == 401

    def test_write_token_can_create_scenario_from_yaml(self, api_client: APIClient, staff_user) -> None:
        raw = _token(staff_user, scopes.CMS_AUTHORING_WRITE)

        response = _bearer(api_client, raw).post(
            YAML_CREATE_URL,
            {"yaml_content": VALID_SCENARIO_YAML},
            format="json",
        )

        assert response.status_code == 201
        assert response.json() == {"scenario_id": "api-created", "name": "API Created"}
        assert Scenario.objects.filter(scenario_id="api-created", created_by=staff_user).exists()

    def test_read_token_cannot_create_scenario_from_yaml(self, api_client: APIClient, staff_user) -> None:
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).post(
            YAML_CREATE_URL,
            {"yaml_content": VALID_SCENARIO_YAML.replace("api-created", "api-read-denied")},
            format="json",
        )

        assert response.status_code == 403
        assert not Scenario.objects.filter(scenario_id="api-read-denied").exists()
