"""Tests for scenario editor services."""

import pytest
from django.contrib.auth import get_user_model

from cms.models import Scenario, ScenarioMetadata
from scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario,
    create_scenario,
    delete_scenario,
    export_scenario_yaml,
    update_metadata,
    update_scenario,
    validate_definition,
    validate_yaml,
)

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@example.com",
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


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
        scenario_id="custom-test",
        name="Custom Test",
        description="A custom test scenario",
        definition=valid_definition,
        created_by=staff_user,
        updated_by=staff_user,
    )


class TestValidateDefinition:
    def test_valid_definition(self):
        errors = validate_definition(
            {
                "id": "test",
                "name": "Test",
                "description": "A test",
                "instances": [
                    {"name": "A", "role": "attacker", "os_type": "kali"},
                ],
            }
        )
        assert errors == []

    def test_missing_required_fields(self):
        errors = validate_definition({})
        assert len(errors) > 0
        assert any("id" in e for e in errors)

    def test_empty_instances(self):
        errors = validate_definition(
            {
                "id": "test",
                "name": "Test",
                "description": "A test",
                "instances": [],
            }
        )
        assert len(errors) > 0

    def test_non_dict_input(self):
        errors = validate_definition("not a dict")
        assert errors == ["Definition must be a JSON object"]

    def test_invalid_subnet_references(self):
        errors = validate_definition(
            {
                "id": "test",
                "name": "Test",
                "description": "A test",
                "instances": [
                    {"name": "A", "role": "attacker", "os_type": "kali"},
                ],
                "subnets": [
                    {"name": "core", "instances": ["A", "NonExistent"]},
                ],
            }
        )
        assert len(errors) > 0
        assert any("NonExistent" in e for e in errors)


class TestValidateYaml:
    def test_valid_yaml(self):
        yaml_str = """
id: test
name: Test
description: A test
instances:
  - name: A
    role: attacker
    os_type: kali
"""
        parsed, errors = validate_yaml(yaml_str)
        assert errors == []
        assert parsed is not None
        assert parsed["id"] == "test"

    def test_invalid_yaml_syntax(self):
        parsed, errors = validate_yaml("invalid: [yaml: {broken")
        assert parsed is None
        assert len(errors) > 0

    def test_yaml_not_mapping(self):
        parsed, errors = validate_yaml("- just\n- a\n- list")
        assert parsed is None
        assert any("mapping" in e for e in errors)

    def test_valid_syntax_invalid_schema(self):
        parsed, errors = validate_yaml("id: test\nname: Test\n")
        assert parsed is None
        assert len(errors) > 0


class TestCreateScenario:
    def test_create_success(self, staff_user, valid_definition):
        scenario = create_scenario(
            staff_user,
            scenario_id="new-scenario",
            name="New Scenario",
            description="Created by test",
            definition=valid_definition,
        )
        assert scenario.scenario_id == "new-scenario"
        assert scenario.name == "New Scenario"
        assert scenario.created_by == staff_user

    def test_collision_with_yaml_default(self, staff_user, valid_definition):
        with pytest.raises(ScenarioEditorError, match="built-in default"):
            create_scenario(
                staff_user,
                scenario_id="basic",
                name="Conflict",
                description="Should fail",
                definition=valid_definition,
            )

    def test_collision_with_existing_custom(self, staff_user, valid_definition, custom_scenario):
        with pytest.raises(ScenarioEditorError, match="already exists"):
            create_scenario(
                staff_user,
                scenario_id="custom-test",
                name="Conflict",
                description="Should fail",
                definition=valid_definition,
            )

    def test_invalid_definition_rejected(self, staff_user):
        with pytest.raises(ScenarioEditorError, match="Invalid"):
            create_scenario(
                staff_user,
                scenario_id="bad-scenario",
                name="Bad",
                description="Bad definition",
                definition={"instances": [], "ngfw": False},
            )


class TestUpdateScenario:
    def test_update_name(self, staff_user, custom_scenario):
        updated = update_scenario(
            staff_user,
            "custom-test",
            name="Updated Name",
        )
        assert updated.name == "Updated Name"

    def test_update_definition(self, staff_user, custom_scenario):
        new_def = {
            "instances": [
                {"name": "Hacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
            ],
            "subnets": [],
            "ngfw": True,
        }
        updated = update_scenario(
            staff_user,
            "custom-test",
            definition=new_def,
        )
        assert updated.definition["ngfw"] is True

    def test_cannot_update_default(self, staff_user):
        with pytest.raises(ScenarioEditorError, match="Cannot edit default"):
            update_scenario(staff_user, "basic", name="Should Fail")

    def test_not_found(self, staff_user):
        with pytest.raises(ScenarioEditorError, match="not found"):
            update_scenario(staff_user, "nonexistent", name="Fail")


class TestDeleteScenario:
    def test_delete_custom(self, staff_user, custom_scenario):
        delete_scenario(staff_user, "custom-test")
        scenario = Scenario.objects.get(pk=custom_scenario.pk)
        assert scenario.deleted_at is not None

    def test_cannot_delete_default(self, staff_user):
        with pytest.raises(ScenarioEditorError, match="Cannot delete default"):
            delete_scenario(staff_user, "basic")

    def test_not_found(self, staff_user):
        with pytest.raises(ScenarioEditorError, match="not found"):
            delete_scenario(staff_user, "nonexistent")

    def test_cleans_up_metadata(self, staff_user, custom_scenario):
        ScenarioMetadata.objects.create(
            scenario_id="custom-test",
            enabled=False,
            updated_by=staff_user,
        )
        delete_scenario(staff_user, "custom-test")
        assert not ScenarioMetadata.objects.filter(scenario_id="custom-test").exists()


class TestUpdateMetadata:
    def test_create_metadata_for_default(self, staff_user, db):
        meta = update_metadata(staff_user, "basic", enabled=False)
        assert meta.scenario_id == "basic"
        assert meta.enabled is False

    def test_update_existing_metadata(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=True,
            staff_only=False,
            updated_by=staff_user,
        )
        meta = update_metadata(staff_user, "basic", staff_only=True)
        assert meta.staff_only is True
        assert meta.enabled is True  # Not changed

    def test_scenario_must_exist(self, staff_user, db):
        with pytest.raises(ScenarioEditorError, match="not found"):
            update_metadata(staff_user, "nonexistent", enabled=False)


class TestCloneScenario:
    def test_clone_default(self, staff_user, db):
        clone = clone_scenario(
            staff_user,
            "basic",
            new_scenario_id="basic-clone",
        )
        assert clone.scenario_id == "basic-clone"
        assert clone.name == "Copy of Basic Range"
        assert len(clone.definition["instances"]) == 2

    def test_clone_custom(self, staff_user, custom_scenario):
        clone = clone_scenario(
            staff_user,
            "custom-test",
            new_scenario_id="custom-clone",
            new_name="My Clone",
        )
        assert clone.scenario_id == "custom-clone"
        assert clone.name == "My Clone"

    def test_clone_source_not_found(self, staff_user, db):
        with pytest.raises(ScenarioEditorError, match="not found"):
            clone_scenario(
                staff_user,
                "nonexistent",
                new_scenario_id="clone",
            )


class TestExportScenarioYaml:
    def test_export_default(self, db):
        yaml_str = export_scenario_yaml("basic")
        assert "id: basic" in yaml_str
        assert "name: Basic Range" in yaml_str
        assert "instances:" in yaml_str

    def test_export_custom(self, custom_scenario):
        yaml_str = export_scenario_yaml("custom-test")
        assert "id: custom-test" in yaml_str

    def test_export_not_found(self, db):
        with pytest.raises(ScenarioEditorError, match="not found"):
            export_scenario_yaml("nonexistent")
