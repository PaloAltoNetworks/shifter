"""Tests for scenario editor template-based views."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from cms.models import Scenario

User = get_user_model()

VIEW_BASE = "/scenario-editor/"


# staff_user, regular_user, staff_client, regular_client, valid_definition from conftest.py


@pytest.fixture
def custom_scenario(staff_user, valid_definition):
    return Scenario.objects.create(
        scenario_id="view-test",
        name="View Test",
        description="Test scenario for views",
        definition=valid_definition,
        created_by=staff_user,
        updated_by=staff_user,
    )


class TestScenarioListView:
    def test_staff_can_access(self, staff_client):
        response = staff_client.get(VIEW_BASE)
        assert response.status_code == 200

    def test_non_staff_redirected(self, regular_client):
        response = regular_client.get(VIEW_BASE)
        # staff_member_required redirects non-staff
        assert response.status_code == 302

    def test_unauthenticated_redirected(self):
        client = Client()
        response = client.get(VIEW_BASE)
        assert response.status_code == 302


class TestScenarioDetailView:
    def test_view_default(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/")
        assert response.status_code == 200

    def test_view_custom(self, staff_client, custom_scenario):
        response = staff_client.get(f"{VIEW_BASE}view-test/")
        assert response.status_code == 200

    def test_not_found(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}nonexistent/")
        assert response.status_code == 404


class TestScenarioCreateFormView:
    def test_get_form(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}create/")
        assert response.status_code == 200

    def test_post_creates_scenario(self, staff_client, valid_definition):
        response = staff_client.post(
            f"{VIEW_BASE}create/",
            {
                "scenario_id": "form-created",
                "name": "Form Created",
                "description": "Created via form",
                "instances_json": json.dumps(valid_definition["instances"]),
                "subnets_json": json.dumps(valid_definition["subnets"]),
            },
        )
        # Should redirect to detail page
        assert response.status_code == 302
        assert Scenario.objects.filter(scenario_id="form-created").exists()

    def test_post_with_errors(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}create/",
            {
                "scenario_id": "",
                "name": "",
                "description": "",
                "instances_json": "[]",
                "subnets_json": "[]",
            },
        )
        assert response.status_code == 200  # Re-renders form with errors


class TestScenarioEditFormView:
    def test_get_form(self, staff_client, custom_scenario):
        response = staff_client.get(f"{VIEW_BASE}view-test/edit/")
        assert response.status_code == 200

    def test_cannot_edit_default(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/edit/")
        assert response.status_code == 403  # Forbidden for default scenarios

    def test_post_updates(self, staff_client, custom_scenario, valid_definition):
        response = staff_client.post(
            f"{VIEW_BASE}view-test/edit/",
            {
                "name": "Updated Via Form",
                "description": "Updated description",
                "instances_json": json.dumps(valid_definition["instances"]),
                "subnets_json": json.dumps(valid_definition["subnets"]),
            },
        )
        assert response.status_code == 302
        custom_scenario.refresh_from_db()
        assert custom_scenario.name == "Updated Via Form"


class TestYAMLEditorView:
    def test_get_editor(self, staff_client, custom_scenario):
        response = staff_client.get(f"{VIEW_BASE}view-test/editor/")
        assert response.status_code == 200

    def test_cannot_edit_default(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/editor/")
        assert response.status_code == 403  # Forbidden for default scenarios


class TestYAMLCreateView:
    def test_get_form(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}create/yaml/")
        assert response.status_code == 200

    def test_post_creates(self, staff_client):
        yaml_content = """
id: yaml-created
name: YAML Created
description: Created via YAML editor
instances:
  - name: Attacker
    role: attacker
    os_type: kali
"""
        response = staff_client.post(
            f"{VIEW_BASE}create/yaml/",
            {
                "yaml_content": yaml_content,
            },
        )
        assert response.status_code == 302
        assert Scenario.objects.filter(scenario_id="yaml-created").exists()


class TestCloneView:
    def test_get_clone_form(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/clone/")
        assert response.status_code == 200

    def test_post_clones(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}basic/clone/",
            {
                "new_scenario_id": "basic-cloned",
                "new_name": "Cloned Basic",
            },
        )
        assert response.status_code == 302
        assert Scenario.objects.filter(scenario_id="basic-cloned").exists()


class TestDeleteView:
    def test_delete_custom(self, staff_client, custom_scenario):
        response = staff_client.post(f"{VIEW_BASE}view-test/delete/")
        assert response.status_code == 302
        custom_scenario.refresh_from_db()
        assert custom_scenario.deleted_at is not None


class TestToggleViews:
    def test_toggle_enabled(self, staff_client):
        response = staff_client.post(f"{VIEW_BASE}basic/toggle-enabled/")
        assert response.status_code == 302

    def test_toggle_staff_only(self, staff_client):
        response = staff_client.post(f"{VIEW_BASE}basic/toggle-staff-only/")
        assert response.status_code == 302


class TestExportView:
    def test_export_yaml(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/export/")
        assert response.status_code == 200
        assert response["Content-Type"] == "text/yaml"
        assert b"id: basic" in response.content

    def test_export_not_found(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}nonexistent/export/")
        assert response.status_code == 404


class TestSlugValidation:
    """Tests for slug format validation on create form."""

    def test_reject_uppercase_slug(self, staff_client, valid_definition):
        response = staff_client.post(
            f"{VIEW_BASE}create/",
            {
                "scenario_id": "Has-Uppercase",
                "name": "Test",
                "description": "Test",
                "instances_json": json.dumps(valid_definition["instances"]),
                "subnets_json": json.dumps(valid_definition["subnets"]),
            },
        )
        assert response.status_code == 200  # Re-renders form with errors

    def test_reject_spaces_in_slug(self, staff_client, valid_definition):
        response = staff_client.post(
            f"{VIEW_BASE}create/",
            {
                "scenario_id": "has spaces",
                "name": "Test",
                "description": "Test",
                "instances_json": json.dumps(valid_definition["instances"]),
                "subnets_json": json.dumps(valid_definition["subnets"]),
            },
        )
        assert response.status_code == 200  # Re-renders form with errors


class TestEmptyFieldValidation:
    """Tests for empty field validation in YAML create."""

    def test_yaml_missing_required_fields(self, staff_client):
        yaml_content = "instances:\n  - name: A\n    role: attacker\n    os_type: kali\n"
        response = staff_client.post(
            f"{VIEW_BASE}create/yaml/",
            {"yaml_content": yaml_content},
        )
        assert response.status_code == 200  # Re-renders form with errors


class TestSuccessMessages:
    """Tests that mutation views set Django messages on success."""

    def test_create_sets_message(self, staff_client, valid_definition):
        response = staff_client.post(
            f"{VIEW_BASE}create/",
            {
                "scenario_id": "msg-test",
                "name": "Message Test",
                "description": "Testing messages",
                "instances_json": json.dumps(valid_definition["instances"]),
                "subnets_json": json.dumps(valid_definition["subnets"]),
            },
            follow=True,
        )
        assert response.status_code == 200
        messages = list(response.context["messages"])
        assert any("created" in str(m).lower() for m in messages)

    def test_delete_sets_message(self, staff_client, custom_scenario):
        response = staff_client.post(
            f"{VIEW_BASE}view-test/delete/",
            follow=True,
        )
        assert response.status_code == 200
        messages = list(response.context["messages"])
        assert any("deleted" in str(m).lower() for m in messages)

    def test_toggle_enabled_sets_message(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}basic/toggle-enabled/",
            follow=True,
        )
        assert response.status_code == 200
        messages = list(response.context["messages"])
        assert len(messages) > 0


class TestJsonScriptContext:
    """Tests that the form editor provides safe JSON context for instances/subnets."""

    def test_edit_form_has_json_script_data(self, staff_client, custom_scenario):
        response = staff_client.get(f"{VIEW_BASE}view-test/edit/")
        assert response.status_code == 200
        content = response.content.decode()
        # json_script renders a <script> tag with the given id
        assert 'id="instances-data"' in content


class TestValidateYamlView:
    """Tests for the YAML validation JSON endpoint used by the UI."""

    def test_valid_yaml(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}validate-yaml/",
            data=json.dumps(
                {
                    "yaml_content": (
                        "id: test\nname: Test\ndescription: A test\n"
                        "instances:\n  - name: A\n    role: attacker\n    os_type: kali\n"
                    )
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True

    def test_invalid_yaml(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}validate-yaml/",
            data=json.dumps({"yaml_content": "invalid: [yaml: {broken"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_bad_request_body(self, staff_client):
        response = staff_client.post(
            f"{VIEW_BASE}validate-yaml/",
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
