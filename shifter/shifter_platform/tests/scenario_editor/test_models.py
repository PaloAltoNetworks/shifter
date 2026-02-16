"""Tests for Scenario and ScenarioMetadata models."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from cms.models import Scenario, ScenarioMetadata

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
            {
                "name": "Attacker",
                "role": "attacker",
                "os_type": "kali",
                "xdr_agent": False,
            },
            {
                "name": "Workstation",
                "role": "victim",
                "os_type": "windows",
                "xdr_agent": True,
            },
        ],
        "subnets": [
            {
                "name": "core",
                "instances": ["Attacker", "Workstation"],
            }
        ],
        "ngfw": False,
    }


class TestScenarioModel:
    def test_create_scenario(self, staff_user, valid_definition):
        scenario = Scenario.objects.create(
            scenario_id="test-scenario",
            name="Test Scenario",
            description="A test scenario.",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        assert scenario.scenario_id == "test-scenario"
        assert scenario.name == "Test Scenario"
        assert scenario.deleted_at is None
        assert not scenario.is_deleted

    def test_str_representation(self, staff_user, valid_definition):
        scenario = Scenario.objects.create(
            scenario_id="test-str",
            name="Test Str",
            description="Test",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        assert str(scenario) == "Test Str (test-str)"

    def test_to_template(self, staff_user, valid_definition):
        scenario = Scenario.objects.create(
            scenario_id="test-template",
            name="Template Test",
            description="Converts to template",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        template = scenario.to_template()
        assert template.id == "test-template"
        assert template.name == "Template Test"
        assert len(template.instances) == 2
        assert len(template.subnets) == 1

    def test_invalid_definition_rejected(self, staff_user):
        """Scenario with empty instances should fail validation."""
        with pytest.raises(PydanticValidationError):
            Scenario.objects.create(
                scenario_id="invalid",
                name="Invalid",
                description="No instances",
                definition={"instances": [], "subnets": [], "ngfw": False},
                created_by=staff_user,
                updated_by=staff_user,
            )

    def test_unique_active_scenario_id(self, staff_user, valid_definition):
        Scenario.objects.create(
            scenario_id="unique-test",
            name="First",
            description="First one",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        with pytest.raises(IntegrityError):
            Scenario.objects.create(
                scenario_id="unique-test",
                name="Second",
                description="Should fail",
                definition=valid_definition,
                created_by=staff_user,
                updated_by=staff_user,
            )

    def test_soft_deleted_allows_reuse(self, staff_user, valid_definition):
        """Soft-deleting frees up the scenario_id for reuse."""
        s1 = Scenario.objects.create(
            scenario_id="reuse-test",
            name="First",
            description="Will be deleted",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        s1.deleted_at = timezone.now()
        # Skip validation for soft-deleted scenario
        Scenario.objects.filter(pk=s1.pk).update(deleted_at=s1.deleted_at)

        # Should succeed since the first is soft-deleted
        s2 = Scenario.objects.create(
            scenario_id="reuse-test",
            name="Second",
            description="Reuses ID",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        assert s2.scenario_id == "reuse-test"

    def test_ordering(self, staff_user, valid_definition):
        Scenario.objects.create(
            scenario_id="z-scenario",
            name="Zebra",
            description="Last",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        Scenario.objects.create(
            scenario_id="a-scenario",
            name="Alpha",
            description="First",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        scenarios = list(Scenario.objects.values_list("name", flat=True))
        assert scenarios == ["Alpha", "Zebra"]


class TestScenarioMetadataModel:
    def test_create_metadata(self, staff_user):
        meta = ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        assert meta.scenario_id == "basic"
        assert not meta.enabled
        assert meta.staff_only

    def test_str_representation(self, staff_user):
        meta = ScenarioMetadata.objects.create(
            scenario_id="test-meta",
            enabled=True,
            staff_only=False,
            updated_by=staff_user,
        )
        assert str(meta) == "test-meta: enabled, all users"

    def test_unique_scenario_id(self, staff_user):
        ScenarioMetadata.objects.create(
            scenario_id="unique-meta",
            updated_by=staff_user,
        )
        with pytest.raises(IntegrityError):
            ScenarioMetadata.objects.create(
                scenario_id="unique-meta",
                updated_by=staff_user,
            )

    def test_defaults(self, staff_user):
        meta = ScenarioMetadata.objects.create(
            scenario_id="defaults",
            updated_by=staff_user,
        )
        assert meta.enabled is True
        assert meta.staff_only is False
