"""Error/branch coverage for the decomposed scenario-editor views.

Drives the create/edit/yaml/clone/toggle/delete/export flows in
``cms.scenario_editor.views`` (including the S1142-extracted ``_handle_*_post``
/ ``_resolve_editable_scenario`` / ``_toggle_scenario_metadata_flag`` helpers)
through the authenticated test client. Registry reads use a real DB scenario so
templates render; only the mutating service calls are patched at the view
module to drive each error path (service error, not-found, default read-only,
and the outer unexpected-error handler).

Fixtures ``staff_client`` / ``staff_user`` / ``valid_definition`` come from
``conftest.py``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cms.models import Scenario
from cms.scenario_editor.services import ScenarioEditorError

pytestmark = pytest.mark.django_db

V = "cms.scenario_editor.views"
BASE = "/scenario-editor/"


@pytest.fixture
def scn(staff_user, valid_definition):
    return Scenario.objects.create(
        scenario_id="view-test",
        name="View Test",
        description="Scenario for view error flows",
        definition=valid_definition,
        created_by=staff_user,
        updated_by=staff_user,
    )


def _create_data(valid_definition, **over):
    data = {
        "scenario_id": "new-scn",
        "name": "New",
        "description": "Desc",
        "ngfw": "on",
        "instances_json": json.dumps(valid_definition["instances"]),
        "subnets_json": json.dumps(valid_definition["subnets"]),
    }
    data.update(over)
    return data


def _edit_data(valid_definition, **over):
    data = {
        "name": "Edited",
        "description": "Desc",
        "ngfw": "on",
        "instances_json": json.dumps(valid_definition["instances"]),
        "subnets_json": json.dumps(valid_definition["subnets"]),
    }
    data.update(over)
    return data


class TestDetailAndExport:
    def test_detail_not_found(self, staff_client):
        resp = staff_client.get(f"{BASE}does-not-exist/")
        assert resp.status_code == 404

    def test_detail_unexpected_error(self, staff_client, scn):
        with patch(f"{V}.export_scenario_yaml", side_effect=RuntimeError("boom")):
            resp = staff_client.get(f"{BASE}{scn.scenario_id}/")
        assert resp.status_code == 500

    def test_export_not_found(self, staff_client):
        with patch(f"{V}.export_scenario_yaml", side_effect=ScenarioEditorError("missing")):
            resp = staff_client.get(f"{BASE}does-not-exist/export/")
        assert resp.status_code == 404

    def test_export_success(self, staff_client, scn):
        resp = staff_client.get(f"{BASE}{scn.scenario_id}/export/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/yaml"

    def test_export_unexpected_error(self, staff_client, scn):
        with patch(f"{V}.export_scenario_yaml", side_effect=RuntimeError("boom")):
            resp = staff_client.get(f"{BASE}{scn.scenario_id}/export/")
        assert resp.status_code == 500


class TestCreate:
    def test_post_invalid_input(self, staff_client):
        resp = staff_client.post(f"{BASE}create/", data={"name": ""})
        assert resp.status_code == 200

    def test_post_service_error(self, staff_client, valid_definition):
        with patch(f"{V}.create_scenario", side_effect=ScenarioEditorError("dup")):
            resp = staff_client.post(f"{BASE}create/", data=_create_data(valid_definition))
        assert resp.status_code == 200

    def test_post_unexpected_error(self, staff_client, valid_definition):
        with patch(f"{V}.create_scenario", side_effect=RuntimeError("boom")):
            resp = staff_client.post(f"{BASE}create/", data=_create_data(valid_definition))
        assert resp.status_code == 500

    def test_post_success(self, staff_client, valid_definition):
        with patch(f"{V}.create_scenario", return_value=None):
            resp = staff_client.post(f"{BASE}create/", data=_create_data(valid_definition))
        assert resp.status_code == 302


class TestEdit:
    def test_default_is_forbidden(self, staff_client):
        resp = staff_client.get(f"{BASE}basic/edit/")
        assert resp.status_code == 403

    def test_not_found(self, staff_client):
        resp = staff_client.get(f"{BASE}does-not-exist/edit/")
        assert resp.status_code == 404

    def test_get_ok(self, staff_client, scn):
        resp = staff_client.get(f"{BASE}{scn.scenario_id}/edit/")
        assert resp.status_code == 200

    def test_post_service_error(self, staff_client, scn, valid_definition):
        with patch(f"{V}.update_scenario", side_effect=ScenarioEditorError("bad")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/edit/", data=_edit_data(valid_definition))
        assert resp.status_code == 200

    def test_post_unexpected_error(self, staff_client, scn, valid_definition):
        with patch(f"{V}.update_scenario", side_effect=RuntimeError("boom")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/edit/", data=_edit_data(valid_definition))
        assert resp.status_code == 500


class TestYaml:
    def test_editor_get(self, staff_client, scn):
        resp = staff_client.get(f"{BASE}{scn.scenario_id}/editor/")
        assert resp.status_code == 200

    def test_editor_post_invalid(self, staff_client, scn):
        with patch(f"{V}.validate_yaml", return_value=(None, ["bad yaml"])):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/editor/", data={"yaml_content": "x"})
        assert resp.status_code == 200

    def test_editor_post_success(self, staff_client, scn):
        with (
            patch(f"{V}.validate_yaml", return_value=({"name": "X"}, [])),
            patch(f"{V}.update_scenario", return_value=None),
        ):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/editor/", data={"yaml_content": "x"})
        assert resp.status_code == 302

    def test_create_post_invalid_yaml(self, staff_client):
        with patch(f"{V}.validate_yaml", return_value=(None, ["bad"])):
            resp = staff_client.post(f"{BASE}create/yaml/", data={"yaml_content": "x"})
        assert resp.status_code == 200

    def test_create_post_missing_fields(self, staff_client):
        with patch(f"{V}.validate_yaml", return_value=({}, [])):
            resp = staff_client.post(f"{BASE}create/yaml/", data={"yaml_content": "x"})
        assert resp.status_code == 200

    def test_create_post_success(self, staff_client):
        parsed = {"id": "new", "name": "N", "description": "D", "instances": [], "subnets": [], "ngfw": False}
        with (
            patch(f"{V}.validate_yaml", return_value=(parsed, [])),
            patch(f"{V}.create_scenario", return_value=None),
        ):
            resp = staff_client.post(f"{BASE}create/yaml/", data={"yaml_content": "x"})
        assert resp.status_code == 302

    def test_validate_endpoint(self, staff_client):
        with patch(f"{V}.validate_yaml", return_value=({"name": "X"}, [])):
            resp = staff_client.post(
                f"{BASE}validate-yaml/", data='{"yaml_content": "x"}', content_type="application/json"
            )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


class TestToggleCloneDelete:
    def test_toggle_enabled_success(self, staff_client, scn):
        with patch(f"{V}.update_metadata", return_value=None):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/toggle-enabled/")
        assert resp.status_code == 302

    def test_toggle_enabled_not_found(self, staff_client):
        resp = staff_client.post(f"{BASE}does-not-exist/toggle-enabled/")
        assert resp.status_code == 404

    def test_toggle_staff_only_service_error(self, staff_client, scn):
        with patch(f"{V}.update_metadata", side_effect=ScenarioEditorError("no")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/toggle-staff-only/")
        assert resp.status_code == 200

    def test_clone_post_missing_id(self, staff_client, scn):
        resp = staff_client.post(f"{BASE}{scn.scenario_id}/clone/", data={})
        assert resp.status_code == 200

    def test_clone_post_service_error(self, staff_client, scn):
        with patch(f"{V}.clone_scenario", side_effect=ScenarioEditorError("dup")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/clone/", data={"new_scenario_id": "copy"})
        assert resp.status_code == 200

    def test_clone_not_found(self, staff_client):
        resp = staff_client.get(f"{BASE}does-not-exist/clone/")
        assert resp.status_code == 404

    def test_delete_service_error(self, staff_client, scn):
        with patch(f"{V}.delete_scenario", side_effect=ScenarioEditorError("locked")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/delete/")
        assert resp.status_code == 200

    def test_delete_unexpected_error(self, staff_client, scn):
        with patch(f"{V}.delete_scenario", side_effect=RuntimeError("boom")):
            resp = staff_client.post(f"{BASE}{scn.scenario_id}/delete/")
        assert resp.status_code == 500
