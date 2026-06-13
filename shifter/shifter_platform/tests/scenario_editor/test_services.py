"""Tests for scenario editor services."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from cms.models import Scenario, ScenarioMetadata
from cms.scenario_editor.services import (
    ScenarioEditorError,
    clone_scenario,
    clone_scenario_from_form_post,
    create_scenario,
    create_scenario_from_form_post,
    create_scenario_from_yaml_post,
    delete_scenario,
    export_scenario_yaml,
    parse_scenario_form_fields,
    update_metadata,
    update_scenario,
    update_scenario_from_form_post,
    update_scenario_from_yaml_post,
    validate_definition,
    validate_yaml,
)

User = get_user_model()


# staff_user, valid_definition from conftest.py


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
        # Scenario.objects (SoftDeleteManager) excludes deleted rows; use
        # all_objects to verify the soft-delete actually landed.
        scenario = Scenario.all_objects.get(pk=custom_scenario.pk)
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

    def test_export_does_not_include_enabled(self, db):
        yaml_str = export_scenario_yaml("basic")
        assert "enabled:" not in yaml_str


class TestUserValidation:
    """Tests for _validate_user enforcement on all service functions.

    The canonical CMS authoring policy (see shared.auth.can_edit_cms_authoring)
    admits active staff users and active Threat Research group members. Other
    authenticated users are rejected at the service layer regardless of how
    they reached it.
    """

    @pytest.mark.parametrize(
        "operation",
        [
            "create",
            "update",
            "delete",
            "clone",
            "metadata",
        ],
    )
    def test_unrelated_user_denied_by_service_layer(self, operation, regular_user, valid_definition):
        calls = {
            "create": lambda: create_scenario(
                regular_user,
                scenario_id="regular-create",
                name="Denied",
                description="Denied",
                definition=valid_definition,
            ),
            "update": lambda: update_scenario(regular_user, "some-id", name="Denied"),
            "delete": lambda: delete_scenario(regular_user, "some-id"),
            "clone": lambda: clone_scenario(regular_user, "some-id", new_scenario_id="clone"),
            "metadata": lambda: update_metadata(regular_user, "some-id", enabled=False),
        }

        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            calls[operation]()

    def test_threat_research_user_admitted_by_service_layer(self, threat_research_user, valid_definition):
        """A non-staff Threat Research user must pass the service auth gate.

        Calls ``create_scenario`` because it is the simplest success path that
        terminates inside the service module (no downstream registry access);
        seeing the scenario persisted proves the auth check did not raise.
        """
        scenario = create_scenario(
            threat_research_user,
            scenario_id="tr-create",
            name="TR Create",
            description="Created by a Threat Research user.",
            definition=valid_definition,
        )
        assert scenario.scenario_id == "tr-create"

    def test_inactive_threat_research_user_denied(self, threat_research_user, valid_definition):
        threat_research_user.is_active = False
        threat_research_user.save(update_fields=["is_active"])
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            create_scenario(
                threat_research_user,
                scenario_id="inactive-tr",
                name="Inactive",
                description="Inactive Threat Research user attempt.",
                definition=valid_definition,
            )

    def test_create_none_user(self, valid_definition):
        with pytest.raises(TypeError, match="cannot be None"):
            create_scenario(
                None,
                scenario_id="test",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_create_unsaved_user(self, valid_definition, db):
        unsaved = User(username="unsaved@example.com", email="unsaved@example.com")
        with pytest.raises(ValueError, match="must be saved"):
            create_scenario(
                unsaved,
                scenario_id="test",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_create_non_user_object(self, valid_definition):
        with pytest.raises(TypeError, match="must be a User instance"):
            create_scenario(
                "not-a-user",
                scenario_id="test",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_update_none_user(self):
        with pytest.raises(TypeError, match="cannot be None"):
            update_scenario(None, "some-id", name="Fail")

    def test_delete_none_user(self):
        with pytest.raises(TypeError, match="cannot be None"):
            delete_scenario(None, "some-id")

    def test_clone_none_user(self):
        with pytest.raises(TypeError, match="cannot be None"):
            clone_scenario(None, "some-id", new_scenario_id="clone")

    def test_metadata_none_user(self):
        with pytest.raises(TypeError, match="cannot be None"):
            update_metadata(None, "some-id", enabled=False)


class TestScenarioIdValidation:
    """Tests for scenario ID format validation."""

    def test_reject_uppercase(self, staff_user, valid_definition):
        with pytest.raises(ScenarioEditorError, match="Invalid scenario ID"):
            create_scenario(
                staff_user,
                scenario_id="Has-Uppercase",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_reject_spaces(self, staff_user, valid_definition):
        with pytest.raises(ScenarioEditorError, match="Invalid scenario ID"):
            create_scenario(
                staff_user,
                scenario_id="has spaces",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_reject_special_chars(self, staff_user, valid_definition):
        with pytest.raises(ScenarioEditorError, match="Invalid scenario ID"):
            create_scenario(
                staff_user,
                scenario_id="bad!id",
                name="Test",
                description="Test",
                definition=valid_definition,
            )

    def test_accept_hyphens_and_underscores(self, staff_user, valid_definition):
        scenario = create_scenario(
            staff_user,
            scenario_id="my-valid_id-123",
            name="Valid",
            description="Valid scenario",
            definition=valid_definition,
        )
        assert scenario.scenario_id == "my-valid_id-123"


class TestScenarioEditorPostHelpers:
    """Tests for service-owned view-flow validation helpers."""

    def _form_data(self, valid_definition, **overrides):
        data = {
            "scenario_id": "form-service-test",
            "name": "Form Service Test",
            "description": "Created through service helper",
            "instances_json": json.dumps(valid_definition["instances"]),
            "subnets_json": json.dumps(valid_definition["subnets"]),
        }
        data.update(overrides)
        return data

    def test_form_parser_returns_context_and_errors(self):
        fields, errors = parse_scenario_form_fields(
            {
                "scenario_id": "Bad ID",
                "name": "",
                "description": "",
                "instances_json": "not json",
            },
            require_id=True,
        )

        assert fields.as_context(include_id=True)["id"] == "Bad ID"
        assert "Name is required" in errors
        assert "Description is required" in errors
        assert "Invalid instances JSON" in errors

    def test_create_from_form_post_creates_scenario(self, staff_user, valid_definition):
        fields, errors = create_scenario_from_form_post(staff_user, self._form_data(valid_definition))

        assert errors == []
        assert fields.scenario_id == "form-service-test"
        assert Scenario.objects.filter(scenario_id="form-service-test").exists()

    def test_update_from_form_post_updates_scenario(self, staff_user, custom_scenario, valid_definition):
        _, errors = update_scenario_from_form_post(
            staff_user,
            custom_scenario.scenario_id,
            self._form_data(valid_definition, name="Updated Helper"),
        )

        assert errors == []
        custom_scenario.refresh_from_db()
        assert custom_scenario.name == "Updated Helper"

    def test_create_from_yaml_post_creates_scenario(self, staff_user):
        yaml_content = """
id: yaml-service-test
name: YAML Service Test
description: Created through service helper
instances:
  - name: A
    role: attacker
    os_type: kali
"""
        fields, errors = create_scenario_from_yaml_post(staff_user, yaml_content)

        assert errors == []
        assert fields is not None
        assert fields.scenario_id == "yaml-service-test"
        assert Scenario.objects.filter(scenario_id="yaml-service-test").exists()

    def test_update_from_yaml_post_updates_scenario(self, staff_user, custom_scenario):
        yaml_content = """
id: custom-test
name: YAML Updated
description: Updated through service helper
instances:
  - name: A
    role: attacker
    os_type: kali
"""
        errors = update_scenario_from_yaml_post(
            staff_user,
            custom_scenario.scenario_id,
            yaml_content,
            fallback_name=custom_scenario.name,
            fallback_description=custom_scenario.description,
        )

        assert errors == []
        custom_scenario.refresh_from_db()
        assert custom_scenario.name == "YAML Updated"

    def test_clone_from_form_post_validates_new_id(self, staff_user):
        scenario, new_name, errors = clone_scenario_from_form_post(staff_user, "basic", {})

        assert scenario is None
        assert new_name is None
        assert errors == ["New scenario ID is required"]


class TestDuplicateIdRaceCondition:
    """Tests for race condition handling in create_scenario."""

    def test_duplicate_id_blocked(self, staff_user, custom_scenario, valid_definition):
        """Creating with an existing ID should fail within the transaction."""
        with pytest.raises(ScenarioEditorError, match="already exists"):
            create_scenario(
                staff_user,
                scenario_id="custom-test",
                name="Duplicate",
                description="Should fail",
                definition=valid_definition,
            )
