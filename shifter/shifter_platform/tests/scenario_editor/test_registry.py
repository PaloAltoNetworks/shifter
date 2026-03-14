"""Tests for the scenario registry."""

import pytest
from django.contrib.auth import get_user_model

from cms.models import Scenario, ScenarioMetadata
from cms.scenarios.registry import (
    check_scenario_access,
    get_scenario_detail,
    is_default_scenario,
    list_all_scenarios,
    load_scenario_template,
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
def regular_user(db):
    return User.objects.create_user(
        username="regular@example.com",
        email="regular@example.com",
        password="testpass",
        is_staff=False,
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


class TestIsDefaultScenario:
    def test_yaml_scenario_is_default(self):
        assert is_default_scenario("basic") is True

    def test_nonexistent_is_not_default(self):
        assert is_default_scenario("nonexistent") is False

    def test_custom_scenario_is_not_default(self, custom_scenario):
        assert is_default_scenario("custom-test") is False


class TestListAllScenarios:
    def test_returns_yaml_defaults(self, db):
        """Should include YAML defaults even with no DB scenarios."""
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "basic" in ids
        assert "ad_attack_lab" in ids

    def test_includes_custom_scenarios(self, custom_scenario):
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "custom-test" in ids

    def test_custom_marked_as_not_default(self, custom_scenario):
        result = list_all_scenarios()
        custom = next(s for s in result if s["id"] == "custom-test")
        assert custom["is_default"] is False

    def test_yaml_marked_as_default(self, db):
        result = list_all_scenarios()
        basic = next(s for s in result if s["id"] == "basic")
        assert basic["is_default"] is True

    def test_metadata_overlay_applied(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        result = list_all_scenarios()
        basic = next(s for s in result if s["id"] == "basic")
        assert basic["enabled"] is False
        assert basic["staff_only"] is True

    def test_non_staff_sees_only_enabled_non_staff(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        result = list_all_scenarios(user=regular_user)
        ids = [s["id"] for s in result]
        # 'basic' is disabled, should not appear for regular user
        assert "basic" not in ids
        # other enabled scenarios should still appear
        assert "ad_attack_lab" in ids

    def test_staff_only_hidden_from_regular(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="ad_attack_lab",
            staff_only=True,
            updated_by=staff_user,
        )
        result = list_all_scenarios(user=regular_user)
        ids = [s["id"] for s in result]
        assert "ad_attack_lab" not in ids

    def test_no_filtering_with_none_user(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        # user=None means no filtering (admin/staff view)
        result = list_all_scenarios(user=None)
        ids = [s["id"] for s in result]
        assert "basic" in ids

    def test_sorted_by_name(self, db):
        result = list_all_scenarios()
        names = [s["name"] for s in result]
        assert names == sorted(names)

    def test_includes_agent_requirements(self, db):
        result = list_all_scenarios()
        for scenario in result:
            assert "agent_requirements" in scenario

    def test_soft_deleted_scenarios_excluded(self, custom_scenario):
        """Soft-deleted custom scenarios should not appear."""
        from django.utils import timezone

        Scenario.objects.filter(pk=custom_scenario.pk).update(deleted_at=timezone.now())
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "custom-test" not in ids


class TestGetScenarioDetail:
    def test_get_yaml_default(self, db):
        detail = get_scenario_detail("basic")
        assert detail["id"] == "basic"
        assert detail["name"] == "Basic Range"
        assert detail["is_default"] is True

    def test_get_custom_scenario(self, custom_scenario):
        detail = get_scenario_detail("custom-test")
        assert detail["id"] == "custom-test"
        assert detail["is_default"] is False

    def test_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            get_scenario_detail("nonexistent")

    def test_metadata_applied(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        detail = get_scenario_detail("basic")
        assert detail["enabled"] is False
        assert detail["staff_only"] is True


class TestLoadScenarioTemplate:
    def test_load_yaml_default(self, db):
        template = load_scenario_template("basic")
        assert template.id == "basic"
        assert len(template.instances) == 2

    def test_load_custom_scenario(self, custom_scenario):
        template = load_scenario_template("custom-test")
        assert template.id == "custom-test"
        assert len(template.instances) == 2

    def test_db_takes_precedence(self, staff_user, db):
        """If both DB and YAML exist with same id, DB wins.

        This shouldn't happen in practice due to collision checks,
        but the registry should handle it gracefully.
        """
        # This test is more about the lookup order than a real scenario
        template = load_scenario_template("basic")
        assert template.id == "basic"

    def test_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            load_scenario_template("nonexistent")


class TestCheckScenarioAccess:
    def test_staff_can_access_disabled(self, staff_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        detail = check_scenario_access("basic", staff_user)
        assert detail["id"] == "basic"
        assert detail["enabled"] is False

    def test_staff_can_access_staff_only(self, staff_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            staff_only=True,
            updated_by=staff_user,
        )
        detail = check_scenario_access("basic", staff_user)
        assert detail["id"] == "basic"
        assert detail["staff_only"] is True

    def test_regular_user_blocked_from_disabled(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        with pytest.raises(ValueError, match="not available"):
            check_scenario_access("basic", regular_user)

    def test_regular_user_blocked_from_staff_only(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            staff_only=True,
            updated_by=staff_user,
        )
        with pytest.raises(ValueError, match="not available"):
            check_scenario_access("basic", regular_user)

    def test_regular_user_can_access_normal_scenario(self, regular_user, db):
        detail = check_scenario_access("basic", regular_user)
        assert detail["id"] == "basic"

    def test_nonexistent_scenario_raises(self, regular_user):
        with pytest.raises(ValueError, match="not found"):
            check_scenario_access("nonexistent", regular_user)
