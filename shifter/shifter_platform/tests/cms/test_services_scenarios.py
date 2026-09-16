"""Behavior tests for the RAES-backed CMS scenario service entrypoints."""

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="svc-scenarios@example.com", email="svc-scenarios@example.com")


class TestListScenarios:
    def test_lists_registered_raes_sources(self, user, hydratable_scenario):
        result = services.list_scenarios(user)

        assert [entry["id"] for entry in result] == [hydratable_scenario.scenario_id]
        assert result[0]["scenario_type"] == "raes"
        assert result[0]["contract_kind"] == "raes"
        assert result[0]["contract_profile"] == "shifter"
        assert result[0]["launchable"] is True

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scenarios(None)

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_scenarios("not_a_user")

    def test_raises_valueerror_for_unsaved_user(self):
        unsaved_user = User(username="unsaved")
        with pytest.raises(ValueError, match="user must be saved"):
            services.list_scenarios(unsaved_user)


class TestGetScenario:
    def test_returns_registered_raes_source(self, hydratable_scenario):
        result = services.get_scenario(hydratable_scenario.scenario_id)

        assert result["id"] == hydratable_scenario.scenario_id
        assert result["scenario_type"] == "raes"
        assert result["launchable"] is True

    def test_raises_for_unknown_scenario(self):
        with pytest.raises(CMSError, match="not found"):
            services.get_scenario("nonexistent")


class TestValidateScenarioRequirements:
    def test_accepts_launchable_raes_source_without_agent(self, hydratable_scenario):
        services.validate_scenario_requirements(hydratable_scenario.scenario_id, None)

    def test_accepts_launchable_raes_source_with_ignored_legacy_agent_shape(
        self, user, make_agent, hydratable_scenario
    ):
        services.validate_scenario_requirements(hydratable_scenario.scenario_id, make_agent(user))

    def test_raises_for_unknown_scenario(self):
        with pytest.raises(CMSError, match="not available for launch"):
            services.validate_scenario_requirements("nonexistent", None)
