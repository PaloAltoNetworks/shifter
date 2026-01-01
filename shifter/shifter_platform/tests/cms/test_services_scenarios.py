"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Logging (debug and error levels)
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import logging

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.models import OperatingSystem
from mission_control.models import AgentConfig

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def agent(user, db):
    """Create an agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Test Agent",
        os=os,
        s3_key="agents/test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=1000,
        sha256_hash="abc123",
    )


@pytest.mark.django_db
class TestListScenarios:
    """Tests for list_scenarios() service function.

    Tests SERVICE behavior:
    - Returns available scenarios with metadata
    - Validates input
    - Logs appropriately
    - Returns consistent structure
    """

    # --- Returns expected scenarios ---

    def test_returns_list(self, user):
        """Service returns a list."""
        result = services.list_scenarios(user)
        assert isinstance(result, list)

    def test_returns_non_empty_list(self, user):
        """Service returns non-empty list of scenarios."""
        result = services.list_scenarios(user)
        assert len(result) > 0

    def test_returns_basic_scenario(self, user):
        """Service includes basic scenario in list."""
        result = services.list_scenarios(user)
        scenario_ids = [s["id"] for s in result]
        assert "basic" in scenario_ids

    def test_returns_ad_attack_lab_scenario(self, user):
        """Service includes ad_attack_lab scenario in list."""
        result = services.list_scenarios(user)
        scenario_ids = [s["id"] for s in result]
        assert "ad_attack_lab" in scenario_ids

    # --- Scenario metadata structure ---

    def test_scenario_has_id(self, user):
        """Each scenario has an id field."""
        result = services.list_scenarios(user)
        for scenario in result:
            assert "id" in scenario
            assert isinstance(scenario["id"], str)

    def test_scenario_has_name(self, user):
        """Each scenario has a name field."""
        result = services.list_scenarios(user)
        for scenario in result:
            assert "name" in scenario
            assert isinstance(scenario["name"], str)
            assert len(scenario["name"]) > 0

    def test_scenario_has_description(self, user):
        """Each scenario has a description field."""
        result = services.list_scenarios(user)
        for scenario in result:
            assert "description" in scenario
            assert isinstance(scenario["description"], str)

    def test_scenario_has_instances(self, user):
        """Each scenario has instances list showing what gets created."""
        result = services.list_scenarios(user)
        for scenario in result:
            assert "instances" in scenario
            assert isinstance(scenario["instances"], list)
            assert len(scenario["instances"]) > 0

    def test_basic_scenario_has_two_instances(self, user):
        """Basic scenario has attacker and victim instances."""
        result = services.list_scenarios(user)
        basic = next((s for s in result if s["id"] == "basic"), None)
        assert basic is not None
        assert len(basic["instances"]) == 2
        roles = [i["role"] for i in basic["instances"]]
        assert "attacker" in roles
        assert "victim" in roles

    def test_ad_attack_lab_has_three_instances(self, user):
        """AD attack lab has attacker, dc, and victim instances."""
        result = services.list_scenarios(user)
        ad_lab = next((s for s in result if s["id"] == "ad_attack_lab"), None)
        assert ad_lab is not None
        assert len(ad_lab["instances"]) == 3
        roles = [i["role"] for i in ad_lab["instances"]]
        assert "attacker" in roles
        assert "dc" in roles
        assert "victim" in roles

    def test_scenario_has_requirements(self, user):
        """Each scenario has requirements field."""
        result = services.list_scenarios(user)
        for scenario in result:
            assert "requirements" in scenario
            assert isinstance(scenario["requirements"], dict)

    def test_ad_attack_lab_requires_windows(self, user):
        """AD attack lab requires Windows agent."""
        result = services.list_scenarios(user)
        ad_lab = next((s for s in result if s["id"] == "ad_attack_lab"), None)
        assert ad_lab is not None
        assert ad_lab["requirements"].get("os") == "windows"

    # --- Input validation ---

    def test_raises_type_error_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.list_scenarios(None)

    def test_raises_type_error_when_user_invalid_type(self):
        """Service raises TypeError when user is not a User instance."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_scenarios("not_a_user")

    def test_raises_value_error_when_user_unsaved(self, db):
        """Service raises ValueError when user has no ID."""
        unsaved_user = User(username="unsaved@example.com")
        with pytest.raises(ValueError, match="user must be saved"):
            services.list_scenarios(unsaved_user)

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with caplog.at_level(logging.DEBUG, logger="cms.services"):
            services.list_scenarios(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with scenario count."""
        with caplog.at_level(logging.DEBUG, logger="cms.services"):
            result = services.list_scenarios(user)
        assert str(len(result)) in caplog.text or "scenario" in caplog.text.lower()

    def test_logs_error_when_user_none(self, caplog):
        """Service logs error when user is None."""
        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_scenarios(None)
        assert "None" in caplog.text

    # --- Consistency guarantees ---

    def test_returns_same_scenarios_on_multiple_calls(self, user):
        """Service returns consistent scenarios on multiple calls."""
        result1 = services.list_scenarios(user)
        result2 = services.list_scenarios(user)
        assert result1 == result2

    def test_scenarios_are_copies_not_references(self, user):
        """Service returns copies to prevent mutation."""
        result1 = services.list_scenarios(user)
        result2 = services.list_scenarios(user)
        # Modify result1
        result1[0]["name"] = "MODIFIED"
        # result2 should not be affected
        assert result2[0]["name"] != "MODIFIED"


@pytest.mark.django_db
class TestGetScenario:
    """Tests for get_scenario() service function."""

    def test_returns_dict(self):
        """Service returns a dictionary."""
        result = services.get_scenario("basic")
        assert isinstance(result, dict)

    def test_returns_basic_scenario(self):
        """Service returns basic scenario by ID."""
        result = services.get_scenario("basic")
        assert result["id"] == "basic"

    def test_returns_ad_attack_lab_scenario(self):
        """Service returns ad_attack_lab scenario by ID."""
        result = services.get_scenario("ad_attack_lab")
        assert result["id"] == "ad_attack_lab"

    def test_raises_for_unknown_scenario(self):
        """Service raises CMSError for unknown scenario ID."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.get_scenario("nonexistent")

    def test_scenario_has_required_fields(self):
        """Returned scenario has all required fields."""
        result = services.get_scenario("basic")
        assert "id" in result
        assert "name" in result
        assert "description" in result
        assert "requirements" in result
        assert "instances" in result


@pytest.mark.django_db
class TestValidateScenarioRequirements:
    """Tests for validate_scenario_requirements() service function."""

    def test_basic_scenario_accepts_any_os(self, agent):
        """Basic scenario accepts agent with any OS."""
        # Should not raise
        services.validate_scenario_requirements("basic", agent)

    def test_ad_attack_lab_accepts_windows_agent(self, user, db):
        """AD attack lab accepts Windows agent."""
        os = OperatingSystem.objects.get(slug="windows")
        agent = AgentConfig.objects.create(
            user=user,
            name="Windows Agent",
            os=os,
            s3_key="agents/test/agent.msi",
            original_filename="agent.msi",
            file_size_bytes=1000,
            sha256_hash="abc123",
        )
        # Should not raise
        services.validate_scenario_requirements("ad_attack_lab", agent)

    def test_ad_attack_lab_rejects_linux_agent(self, user, db):
        """AD attack lab rejects Linux agent."""
        from cms.exceptions import CMSError

        os = OperatingSystem.objects.get(slug="linux-debian")
        agent = AgentConfig.objects.create(
            user=user,
            name="Linux Agent",
            os=os,
            s3_key="agents/test/agent.deb",
            original_filename="agent.deb",
            file_size_bytes=1000,
            sha256_hash="abc123",
        )
        with pytest.raises(CMSError, match=r"(?i)requires.*windows"):
            services.validate_scenario_requirements("ad_attack_lab", agent)

    def test_raises_for_unknown_scenario(self, agent):
        """Service raises CMSError for unknown scenario ID."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.validate_scenario_requirements("nonexistent", agent)

    def test_raises_when_agent_is_none_and_required(self):
        """Service raises CMSError when agent is None but required."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="requires an agent"):
            services.validate_scenario_requirements("basic", None)
