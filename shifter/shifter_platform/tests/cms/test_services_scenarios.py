"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.models import AgentConfig, OperatingSystem
from shared.constants import USER_CANNOT_BE_NONE

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

    def test_returns_non_empty_list_of_scenarios(self, user):
        """Service returns a non-empty list of scenarios."""
        result = services.list_scenarios(user)
        assert isinstance(result, list)
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

    def test_scenarios_have_required_metadata(self, user):
        """Each scenario has required metadata fields with correct types."""
        result = services.list_scenarios(user)
        for scenario in result:
            # Required fields
            assert isinstance(scenario["id"], str)
            assert isinstance(scenario["name"], str) and len(scenario["name"]) > 0
            assert isinstance(scenario["description"], str)
            assert isinstance(scenario["instances"], list) and len(scenario["instances"]) > 0

            # Agent requirements structure
            reqs = scenario["agent_requirements"]
            assert isinstance(reqs, dict)
            assert "has_from_agent" in reqs
            assert "requires_windows" in reqs
            assert "requires_linux" in reqs

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

    def test_ad_attack_lab_has_from_agent(self, user):
        """AD attack lab uses from_agent for victim."""
        result = services.list_scenarios(user)
        ad_lab = next((s for s in result if s["id"] == "ad_attack_lab"), None)
        assert ad_lab is not None
        assert ad_lab["agent_requirements"]["has_from_agent"] is True

    # --- Input validation ---

    def test_validates_user_parameter(self, db):
        """Service validates user parameter."""
        # None user
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scenarios(None)

        # Invalid type
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_scenarios("not_a_user")

        # Unsaved user (no ID)
        unsaved_user = User(username="unsaved@example.com")
        with pytest.raises(ValueError, match="user must be saved"):
            services.list_scenarios(unsaved_user)

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
        assert "enabled" in result
        assert "ngfw" in result
        assert "instances" in result


@pytest.mark.django_db
class TestValidateScenarioRequirements:
    """Tests for validate_scenario_requirements() service function.

    Note: With multi-agent support, OS validation happens at create_range time
    based on get_agent_requirements(), not in validate_scenario_requirements.
    """

    def test_basic_scenario_accepts_any_os(self, agent):
        """Basic scenario accepts agent with any OS (from_agent)."""
        # Should not raise
        services.validate_scenario_requirements("basic", agent)

    def test_ad_attack_lab_accepts_windows_agent(self, user, db):
        """AD attack lab accepts Windows agent (from_agent)."""
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

    def test_ad_attack_lab_accepts_linux_agent(self, user, db):
        """AD attack lab accepts Linux agent (from_agent allows any OS)."""
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
        # Should not raise - from_agent accepts any OS
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
