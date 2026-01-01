"""Tests for CMS scenario template loader.

Tests the loader module that reads and validates YAML templates:
- load_scenario: Load a single scenario by ID
- list_scenario_ids: Get list of available scenario IDs
- get_all_scenarios: Get all scenarios as ScenarioTemplate list
"""

import pytest


class TestLoadScenario:
    """Tests for load_scenario() function."""

    def test_import_load_scenario(self):
        """load_scenario can be imported from cms.scenarios.loader."""
        from cms.scenarios.loader import load_scenario

        assert load_scenario is not None

    def test_load_basic_scenario(self):
        """load_scenario returns ScenarioTemplate for 'basic'."""
        from cms.scenarios.loader import load_scenario
        from cms.scenarios.schema import ScenarioTemplate

        scenario = load_scenario("basic")
        assert isinstance(scenario, ScenarioTemplate)
        assert scenario.id == "basic"

    def test_load_ad_attack_lab_scenario(self):
        """load_scenario returns ScenarioTemplate for 'ad_attack_lab'."""
        from cms.scenarios.loader import load_scenario
        from cms.scenarios.schema import ScenarioTemplate

        scenario = load_scenario("ad_attack_lab")
        assert isinstance(scenario, ScenarioTemplate)
        assert scenario.id == "ad_attack_lab"

    def test_load_nonexistent_scenario_raises(self):
        """load_scenario raises ValueError for unknown scenario ID."""
        from cms.scenarios.loader import load_scenario

        with pytest.raises(ValueError, match="not found"):
            load_scenario("nonexistent_scenario")

    def test_basic_scenario_has_attacker_instance(self):
        """Basic scenario has an attacker instance."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("basic")
        roles = [i.role for i in scenario.instances]
        assert "attacker" in roles

    def test_basic_scenario_has_victim_instance(self):
        """Basic scenario has a victim instance."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("basic")
        roles = [i.role for i in scenario.instances]
        assert "victim" in roles

    def test_basic_scenario_requires_agent(self):
        """Basic scenario requires an agent."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("basic")
        assert scenario.requirements.required is True

    def test_basic_scenario_accepts_any_os(self):
        """Basic scenario accepts any OS (os=None)."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("basic")
        assert scenario.requirements.os is None

    def test_ad_attack_lab_has_dc_instance(self):
        """AD attack lab has a domain controller instance."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("ad_attack_lab")
        roles = [i.role for i in scenario.instances]
        assert "dc" in roles

    def test_ad_attack_lab_requires_windows(self):
        """AD attack lab requires Windows agent."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("ad_attack_lab")
        assert scenario.requirements.os == "windows"

    def test_ad_attack_lab_dc_has_config(self):
        """AD attack lab DC instance has domain configuration."""
        from cms.scenarios.loader import load_scenario

        scenario = load_scenario("ad_attack_lab")
        dc = next(i for i in scenario.instances if i.role == "dc")
        assert dc.domain_controller is True
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name is not None


class TestListScenarioIds:
    """Tests for list_scenario_ids() function."""

    def test_import_list_scenario_ids(self):
        """list_scenario_ids can be imported from cms.scenarios.loader."""
        from cms.scenarios.loader import list_scenario_ids

        assert list_scenario_ids is not None

    def test_returns_list(self):
        """list_scenario_ids returns a list."""
        from cms.scenarios.loader import list_scenario_ids

        result = list_scenario_ids()
        assert isinstance(result, list)

    def test_returns_non_empty_list(self):
        """list_scenario_ids returns non-empty list."""
        from cms.scenarios.loader import list_scenario_ids

        result = list_scenario_ids()
        assert len(result) > 0

    def test_includes_basic(self):
        """list_scenario_ids includes 'basic'."""
        from cms.scenarios.loader import list_scenario_ids

        result = list_scenario_ids()
        assert "basic" in result

    def test_includes_ad_attack_lab(self):
        """list_scenario_ids includes 'ad_attack_lab'."""
        from cms.scenarios.loader import list_scenario_ids

        result = list_scenario_ids()
        assert "ad_attack_lab" in result

    def test_returns_strings(self):
        """list_scenario_ids returns list of strings."""
        from cms.scenarios.loader import list_scenario_ids

        result = list_scenario_ids()
        for item in result:
            assert isinstance(item, str)


class TestGetAllScenarios:
    """Tests for get_all_scenarios() function."""

    def test_import_get_all_scenarios(self):
        """get_all_scenarios can be imported from cms.scenarios.loader."""
        from cms.scenarios.loader import get_all_scenarios

        assert get_all_scenarios is not None

    def test_returns_list(self):
        """get_all_scenarios returns a list."""
        from cms.scenarios.loader import get_all_scenarios

        result = get_all_scenarios()
        assert isinstance(result, list)

    def test_returns_scenario_templates(self):
        """get_all_scenarios returns list of ScenarioTemplate."""
        from cms.scenarios.loader import get_all_scenarios
        from cms.scenarios.schema import ScenarioTemplate

        result = get_all_scenarios()
        for scenario in result:
            assert isinstance(scenario, ScenarioTemplate)

    def test_includes_basic_scenario(self):
        """get_all_scenarios includes basic scenario."""
        from cms.scenarios.loader import get_all_scenarios

        result = get_all_scenarios()
        ids = [s.id for s in result]
        assert "basic" in ids

    def test_includes_ad_attack_lab_scenario(self):
        """get_all_scenarios includes ad_attack_lab scenario."""
        from cms.scenarios.loader import get_all_scenarios

        result = get_all_scenarios()
        ids = [s.id for s in result]
        assert "ad_attack_lab" in ids

    def test_returns_same_count_as_list_ids(self):
        """get_all_scenarios returns same count as list_scenario_ids."""
        from cms.scenarios.loader import get_all_scenarios, list_scenario_ids

        scenarios = get_all_scenarios()
        ids = list_scenario_ids()
        assert len(scenarios) == len(ids)

    def test_scenarios_are_valid(self):
        """All returned scenarios have required fields."""
        from cms.scenarios.loader import get_all_scenarios

        result = get_all_scenarios()
        for scenario in result:
            assert scenario.id
            assert scenario.name
            assert scenario.description
            assert scenario.requirements is not None
            assert len(scenario.instances) > 0
