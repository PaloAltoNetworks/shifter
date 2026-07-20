"""Behavior tests for the cms.services scenario entrypoints.

Drives ``list_scenarios`` / ``get_scenario`` / ``validate_scenario_requirements``
against the real scenario registry (built-in templates + DB customs) and real
``AgentConfig`` rows, instead of patching ``cms.scenarios.registry.*``.
"""

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()

# A real built-in scenario whose template requires an agent (NGFW victim).
_AGENT_REQUIRED_SCENARIO = "basic_ngfw"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="svc-scenarios@example.com", email="svc-scenarios@example.com")


class TestListScenarios:
    def test_returns_non_empty_list(self, user):
        result = services.list_scenarios(user)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_includes_builtin_scenarios(self, user):
        ids = {s["id"] for s in services.list_scenarios(user)}
        assert {"basic", "ad_attack_lab"} <= ids

    def test_scenarios_have_required_metadata(self, user):
        for scenario in services.list_scenarios(user):
            assert isinstance(scenario["id"], str)
            assert isinstance(scenario["name"], str) and scenario["name"]
            assert isinstance(scenario["description"], str)
            assert isinstance(scenario["instances"], list) and scenario["instances"]
            reqs = scenario["agent_requirements"]
            assert {"has_from_agent", "requires_windows", "requires_linux"} <= set(reqs)

    def test_basic_has_attacker_and_victim(self, user):
        basic = next(s for s in services.list_scenarios(user) if s["id"] == "basic")
        roles = {i["role"] for i in basic["instances"]}
        assert {"attacker", "victim"} <= roles

    def test_ad_attack_lab_has_dc(self, user):
        ad = next(s for s in services.list_scenarios(user) if s["id"] == "ad_attack_lab")
        roles = {i["role"] for i in ad["instances"]}
        assert {"attacker", "dc", "victim"} <= roles

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scenarios(None)

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_scenarios("not_a_user")

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must be saved"):
            services.list_scenarios(User(username="unsaved"))


class TestGetScenario:
    def test_returns_basic(self):
        result = services.get_scenario("basic")
        assert isinstance(result, dict)
        assert result["id"] == "basic"

    def test_returns_ad_attack_lab(self):
        assert services.get_scenario("ad_attack_lab")["id"] == "ad_attack_lab"

    def test_has_required_fields(self):
        result = services.get_scenario("basic")
        assert {"id", "name", "description", "enabled", "ngfw", "instances"} <= set(result)

    def test_raises_for_unknown_scenario(self):
        with pytest.raises(CMSError, match="not found"):
            services.get_scenario("nonexistent")


class TestValidateScenarioRequirements:
    def test_accepts_agent_for_basic(self, user, make_agent):
        services.validate_scenario_requirements("basic", make_agent(user))  # no raise

    def test_basic_accepts_none_agent(self):
        # `basic` does not require an agent, so a missing agent is fine.
        services.validate_scenario_requirements("basic", None)  # no raise

    def test_accepts_agent_for_agent_required_scenario(self, user, make_agent):
        services.validate_scenario_requirements(_AGENT_REQUIRED_SCENARIO, make_agent(user))  # no raise

    def test_raises_when_agent_required_but_none(self):
        with pytest.raises(CMSError, match="requires an agent"):
            services.validate_scenario_requirements(_AGENT_REQUIRED_SCENARIO, None)

    def test_raises_for_unknown_scenario(self, user, make_agent):
        with pytest.raises(CMSError, match="not found"):
            services.validate_scenario_requirements("nonexistent", make_agent(user))
