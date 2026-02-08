"""Tests for scenario editor API views."""

import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from cms.models import Scenario, ScenarioMetadata

User = get_user_model()

API_BASE = "/scenario-editor/api/"


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@example.com",
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="regular@example.com",
        email="regular@example.com",
        password="testpass",
        is_staff=False,
    )


@pytest.fixture
def staff_client(staff_user):
    client = Client()
    client.force_login(staff_user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def regular_client(regular_user):
    client = Client()
    client.force_login(regular_user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def valid_definition():
    return {
        "instances": [
            {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
            {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
        ],
        "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
        "ngfw": False,
    }


@pytest.fixture
def custom_scenario(staff_user, valid_definition):
    return Scenario.objects.create(
        scenario_id="api-test",
        name="API Test",
        description="Test scenario for API",
        definition=valid_definition,
        created_by=staff_user,
        updated_by=staff_user,
    )


class TestScenarioListAPI:
    def test_staff_can_list(self, staff_client):
        response = staff_client.get(API_BASE)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert any(s["id"] == "basic" for s in data)

    def test_non_staff_forbidden(self, regular_client):
        response = regular_client.get(API_BASE)
        assert response.status_code == 403

    def test_unauthenticated_forbidden(self):
        client = Client()
        response = client.get(API_BASE)
        # DRF SessionAuthentication returns 401 for unauthenticated,
        # 403 for authenticated but lacking permission
        assert response.status_code in (401, 403)


class TestScenarioCreateAPI:
    def test_create_success(self, staff_client, valid_definition):
        response = staff_client.post(
            f"{API_BASE}create/",
            data=json.dumps({
                "scenario_id": "api-created",
                "name": "API Created",
                "description": "Created via API",
                "definition": valid_definition,
            }),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "api-created"

    def test_create_invalid_definition(self, staff_client):
        response = staff_client.post(
            f"{API_BASE}create/",
            data=json.dumps({
                "scenario_id": "bad",
                "name": "Bad",
                "description": "Bad definition",
                "definition": {"instances": [], "ngfw": False},
            }),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_non_staff_forbidden(self, regular_client, valid_definition):
        response = regular_client.post(
            f"{API_BASE}create/",
            data=json.dumps({
                "scenario_id": "blocked",
                "name": "Blocked",
                "description": "Should fail",
                "definition": valid_definition,
            }),
            content_type="application/json",
        )
        assert response.status_code == 403


class TestScenarioDetailAPI:
    def test_get_default(self, staff_client):
        response = staff_client.get(f"{API_BASE}basic/")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "basic"
        assert data["is_default"] is True

    def test_get_custom(self, staff_client, custom_scenario):
        response = staff_client.get(f"{API_BASE}api-test/")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "api-test"
        assert data["is_default"] is False

    def test_not_found(self, staff_client):
        response = staff_client.get(f"{API_BASE}nonexistent/")
        assert response.status_code == 404


class TestScenarioUpdateAPI:
    def test_patch_name(self, staff_client, custom_scenario):
        response = staff_client.patch(
            f"{API_BASE}api-test/update/",
            data=json.dumps({"name": "Updated Name"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_cannot_update_default(self, staff_client):
        response = staff_client.patch(
            f"{API_BASE}basic/update/",
            data=json.dumps({"name": "Fail"}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestScenarioDeleteAPI:
    def test_delete_custom(self, staff_client, custom_scenario):
        response = staff_client.delete(f"{API_BASE}api-test/delete/")
        assert response.status_code == 204

    def test_cannot_delete_default(self, staff_client):
        response = staff_client.delete(f"{API_BASE}basic/delete/")
        assert response.status_code == 400


class TestScenarioValidateAPI:
    def test_valid_definition(self, staff_client):
        response = staff_client.post(
            f"{API_BASE}validate/",
            data=json.dumps({
                "definition": {
                    "id": "test",
                    "name": "Test",
                    "description": "A test",
                    "instances": [
                        {"name": "A", "role": "attacker", "os_type": "kali"},
                    ],
                }
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_invalid_definition(self, staff_client):
        response = staff_client.post(
            f"{API_BASE}validate/",
            data=json.dumps({"definition": {"id": "bad"}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


class TestScenarioMetadataAPI:
    def test_update_metadata(self, staff_client):
        response = staff_client.patch(
            f"{API_BASE}basic/metadata/",
            data=json.dumps({"enabled": False, "staff_only": True}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["staff_only"] is True

    def test_must_provide_at_least_one_field(self, staff_client):
        response = staff_client.patch(
            f"{API_BASE}basic/metadata/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestScenarioCloneAPI:
    def test_clone_default(self, staff_client):
        response = staff_client.post(
            f"{API_BASE}basic/clone/",
            data=json.dumps({
                "new_scenario_id": "basic-api-clone",
                "new_name": "API Clone",
            }),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "basic-api-clone"


class TestScenarioExportAPI:
    def test_export_yaml(self, staff_client):
        response = staff_client.get(f"{API_BASE}basic/export-yaml/")
        assert response.status_code == 200
        data = response.json()
        assert "yaml" in data
        assert "id: basic" in data["yaml"]
