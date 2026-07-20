"""DRF boundary coverage for the canonical Scenario Editor API (issue #1371).

These endpoints wrap the already-audited ``cms.scenario_editor.services`` facade
so the platform SPA can browse/create/edit/validate/save scenarios without ever
calling the legacy ``/scenario-editor/`` Django form/action routes. Coverage
here drives the enforcement boundaries (CMS authoring scope, source-capability
rules) rather than re-testing the service layer, which owns domain correctness.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from cms.models import AcesPackageSource, Scenario, ScenarioMetadata
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = pytest.mark.django_db

SCENARIOS_URL = "/api/v1/cms/scenario-editor/scenarios/"


def _detail_url(scenario_id: str) -> str:
    return f"{SCENARIOS_URL}{scenario_id}/"


def _clone_url(scenario_id: str) -> str:
    return f"{SCENARIOS_URL}{scenario_id}/clone/"


def _metadata_url(scenario_id: str) -> str:
    return f"{SCENARIOS_URL}{scenario_id}/metadata/"


def _export_url(scenario_id: str) -> str:
    return f"{SCENARIOS_URL}{scenario_id}/export/"


_DEFINITION = {
    "ngfw": False,
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Victim", "role": "victim", "os_type": "from_agent", "xdr_agent": False},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Victim"]}],
}


def _create_body(scenario_id: str = "my-lab", name: str = "My Lab") -> dict:
    return {
        "scenario_id": scenario_id,
        "name": name,
        "description": "A custom lab.",
        **_DEFINITION,
    }


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def authoring_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="scenario-api@example.com",
        email="scenario-api@example.com",
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def custom_scenario(authoring_user) -> Scenario:
    return Scenario.objects.create(
        scenario_id="existing-lab",
        name="Existing Lab",
        description="Pre-existing custom scenario.",
        definition=_DEFINITION,
        created_by=authoring_user,
        updated_by=authoring_user,
    )


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="scenario-api", created_by=user, scopes=list(granted_scopes))
    return raw


class TestScenarioCreate:
    def test_authoring_actor_creates_structured_scenario(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.post(SCENARIOS_URL, _create_body(), format="json")

        assert response.status_code == 201
        assert response.json()["scenario_id"] == "my-lab"
        assert Scenario.objects.filter(scenario_id="my-lab").exists()

    def test_invalid_definition_returns_validation_errors(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)
        body = _create_body()
        body["instances"] = []  # schema requires at least one instance

        response = api_client.post(SCENARIOS_URL, body, format="json")

        assert response.status_code == 400
        assert response.json()["error"]["code"] in {"invalid", "validation_error"}

    def test_duplicate_scenario_id_is_rejected(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.post(SCENARIOS_URL, _create_body(scenario_id="existing-lab"), format="json")

        assert response.status_code == 400

    def test_anonymous_cannot_create(self, api_client):
        response = api_client.post(SCENARIOS_URL, _create_body(), format="json")

        assert response.status_code in {401, 403}

    def test_read_scope_token_cannot_create(self, api_client, authoring_user):
        raw = _token(authoring_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).post(SCENARIOS_URL, _create_body(), format="json")

        assert response.status_code == 403
        assert not Scenario.objects.filter(scenario_id="my-lab").exists()


class TestScenarioDetail:
    def test_custom_scenario_detail_is_editable(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_detail_url("existing-lab"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "custom"
        assert payload["editable"] is True
        assert payload["deletable"] is True
        assert [i["name"] for i in payload["instances"]] == ["Attacker", "Victim"]

    def test_builtin_scenario_detail_is_read_only(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_detail_url("basic"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "builtin"
        assert payload["is_default"] is True
        assert payload["editable"] is False
        assert payload["deletable"] is False
        assert payload["exportable"] is True

    def test_aces_scenario_detail_is_read_only_with_provenance(self, api_client, authoring_user):
        AcesPackageSource.objects.create(
            scenario_id="polaris-aces",
            contract_kind="aces",
            contract_profile="shifter",
            package_ref="content-packages/polaris",
            package_version="1.0.0",
            package_digest="sha256:" + "a" * 64,
            conformance_status="passed",
            provenance={"repo": "acme/aces"},
            registered_by=authoring_user,
        )
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_detail_url("polaris-aces"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "aces"
        assert payload["editable"] is False
        assert payload["aces"]["contract_kind"] == "aces"

    def test_unknown_scenario_returns_404(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_detail_url("does-not-exist"))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_catalog_list_carries_server_owned_source(self, api_client, authoring_user, custom_scenario):
        # The catalog list carries the single server-owned `source` classification
        # so the SPA never re-derives it from scenario_type / is_default.
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get("/api/v1/cms/catalog/")

        assert response.status_code == 200
        by_id = {entry["id"]: entry for entry in response.json()}
        assert by_id["basic"]["source"] == "builtin"
        assert by_id["existing-lab"]["source"] == "custom"


class TestScenarioUpdate:
    def test_authoring_actor_updates_custom_scenario(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)
        body = {"name": "Renamed Lab", "description": "Updated.", **_DEFINITION}

        response = api_client.patch(_detail_url("existing-lab"), body, format="json")

        assert response.status_code == 200
        custom_scenario.refresh_from_db()
        assert custom_scenario.name == "Renamed Lab"

    def test_cannot_update_builtin_default(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)
        body = {"name": "Hacked", "description": "x", **_DEFINITION}

        response = api_client.patch(_detail_url("basic"), body, format="json")

        assert response.status_code in {400, 403, 409}
        assert not Scenario.objects.filter(scenario_id="basic").exists()

    def test_read_scope_token_cannot_update(self, api_client, authoring_user, custom_scenario):
        raw = _token(authoring_user, scopes.CMS_AUTHORING_READ)
        body = {"name": "Nope", "description": "x", **_DEFINITION}

        response = _bearer(api_client, raw).patch(_detail_url("existing-lab"), body, format="json")

        assert response.status_code == 403
        custom_scenario.refresh_from_db()
        assert custom_scenario.name == "Existing Lab"


class TestScenarioDelete:
    def test_authoring_actor_soft_deletes_custom_scenario(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.delete(_detail_url("existing-lab"))

        assert response.status_code == 204
        assert not Scenario.objects.filter(scenario_id="existing-lab").exists()
        assert Scenario.all_objects.filter(scenario_id="existing-lab").exists()

    def test_cannot_delete_builtin_default(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.delete(_detail_url("basic"))

        assert response.status_code in {400, 403, 409}


class TestScenarioClone:
    def test_clone_creates_new_custom_scenario(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.post(
            _clone_url("basic"),
            {"new_scenario_id": "basic-copy", "new_name": "Basic Copy"},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["scenario_id"] == "basic-copy"
        assert Scenario.objects.filter(scenario_id="basic-copy").exists()


class TestScenarioMetadata:
    def test_metadata_update_sets_enabled_and_staff_only(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.patch(
            _metadata_url("existing-lab"),
            {"enabled": False, "staff_only": True},
            format="json",
        )

        assert response.status_code == 200
        meta = ScenarioMetadata.objects.get(scenario_id="existing-lab")
        assert meta.enabled is False
        assert meta.staff_only is True

    def test_read_scope_token_cannot_update_metadata(self, api_client, authoring_user, custom_scenario):
        raw = _token(authoring_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).patch(_metadata_url("existing-lab"), {"enabled": False}, format="json")

        assert response.status_code == 403


class TestScenarioExport:
    def test_export_returns_yaml(self, api_client, authoring_user, custom_scenario):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_export_url("existing-lab"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_id"] == "existing-lab"
        assert "id: existing-lab" in payload["yaml"]

    def test_export_unknown_returns_404(self, api_client, authoring_user):
        api_client.force_authenticate(user=authoring_user)

        response = api_client.get(_export_url("does-not-exist"))

        assert response.status_code == 404
