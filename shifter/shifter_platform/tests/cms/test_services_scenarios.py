"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from cms import services
from shared.constants import USER_CANNOT_BE_NONE


@pytest.fixture
def user():
    mock = Mock()
    mock.pk = 42
    mock.id = 42
    mock.email = "test@example.com"
    mock.is_staff = False
    mock.is_superuser = False
    return mock


@pytest.fixture
def agent(user):
    """Create a mock agent for testing."""
    mock_os = Mock()
    mock_os.slug = "windows"
    mock = Mock()
    mock.pk = 1
    mock.id = 1
    mock.user = user
    mock.name = "Test Agent"
    mock.os = mock_os
    mock.s3_key = "agents/test/agent.msi"
    mock.original_filename = "agent.msi"
    mock.file_size_bytes = 1000
    mock.sha256_hash = "abc123"
    return mock


# Canned scenario data matching the real registry output
BASIC_SCENARIO = {
    "id": "basic",
    "name": "Basic Scenario",
    "description": "Basic attacker/victim scenario",
    "enabled": True,
    "staff_only": False,
    "is_default": True,
    "ngfw": False,
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali"},
        {"name": "Victim", "role": "victim", "os_type": "from_agent"},
    ],
    "agent_requirements": {
        "has_from_agent": True,
        "requires_windows": False,
        "requires_linux": False,
    },
}

AD_ATTACK_LAB_SCENARIO = {
    "id": "ad_attack_lab",
    "name": "AD Attack Lab",
    "description": "Active Directory attack scenario",
    "enabled": True,
    "staff_only": False,
    "is_default": True,
    "ngfw": False,
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali"},
        {"name": "DC", "role": "dc", "os_type": "windows-server-2022"},
        {"name": "Victim", "role": "victim", "os_type": "from_agent"},
    ],
    "agent_requirements": {
        "has_from_agent": True,
        "requires_windows": False,
        "requires_linux": False,
    },
}

CANNED_SCENARIOS = [AD_ATTACK_LAB_SCENARIO, BASIC_SCENARIO]


class TestListScenarios:
    """Tests for list_scenarios() service function.

    Tests SERVICE behavior:
    - Returns available scenarios with metadata
    - Validates input
    - Logs appropriately
    - Returns consistent structure
    """

    # --- Returns expected scenarios ---

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_returns_non_empty_list_of_scenarios(self, _mock_registry, user):
        """Service returns a non-empty list of scenarios."""
        result = services.list_scenarios(user)
        assert isinstance(result, list)
        assert len(result) > 0

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_returns_basic_scenario(self, _mock_registry, user):
        """Service includes basic scenario in list."""
        result = services.list_scenarios(user)
        scenario_ids = [s["id"] for s in result]
        assert "basic" in scenario_ids

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_returns_ad_attack_lab_scenario(self, _mock_registry, user):
        """Service includes ad_attack_lab scenario in list."""
        result = services.list_scenarios(user)
        scenario_ids = [s["id"] for s in result]
        assert "ad_attack_lab" in scenario_ids

    # --- Scenario metadata structure ---

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_scenarios_have_required_metadata(self, _mock_registry, user):
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

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_basic_scenario_has_two_instances(self, _mock_registry, user):
        """Basic scenario has attacker and victim instances."""
        result = services.list_scenarios(user)
        basic = next((s for s in result if s["id"] == "basic"), None)
        assert basic is not None
        assert len(basic["instances"]) == 2
        roles = [i["role"] for i in basic["instances"]]
        assert "attacker" in roles
        assert "victim" in roles

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_ad_attack_lab_has_three_instances(self, _mock_registry, user):
        """AD attack lab has attacker, dc, and victim instances."""
        result = services.list_scenarios(user)
        ad_lab = next((s for s in result if s["id"] == "ad_attack_lab"), None)
        assert ad_lab is not None
        assert len(ad_lab["instances"]) == 3
        roles = [i["role"] for i in ad_lab["instances"]]
        assert "attacker" in roles
        assert "dc" in roles
        assert "victim" in roles

    @patch("cms.scenarios.registry.list_all_scenarios", return_value=CANNED_SCENARIOS)
    def test_ad_attack_lab_has_from_agent(self, _mock_registry, user):
        """AD attack lab uses from_agent for victim."""
        result = services.list_scenarios(user)
        ad_lab = next((s for s in result if s["id"] == "ad_attack_lab"), None)
        assert ad_lab is not None
        assert ad_lab["agent_requirements"]["has_from_agent"] is True

    # --- Input validation ---

    def test_validates_user_parameter(self):
        """Service validates user parameter."""
        # None user
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scenarios(None)

        # Invalid type
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_scenarios("not_a_user")

        # Unsaved user (no ID)
        unsaved_user = MagicMock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.list_scenarios(unsaved_user)

    # --- Consistency guarantees ---

    def test_returns_same_scenarios_on_multiple_calls(self, user):
        """Service returns consistent scenarios on multiple calls."""
        import copy

        canned = [copy.deepcopy(s) for s in CANNED_SCENARIOS]
        with patch("cms.scenarios.registry.list_all_scenarios", return_value=canned):
            result1 = services.list_scenarios(user)
        canned2 = [copy.deepcopy(s) for s in CANNED_SCENARIOS]
        with patch("cms.scenarios.registry.list_all_scenarios", return_value=canned2):
            result2 = services.list_scenarios(user)
        assert result1 == result2

    def test_scenarios_are_copies_not_references(self, user):
        """Service returns copies to prevent mutation."""
        import copy

        canned = [copy.deepcopy(s) for s in CANNED_SCENARIOS]
        with patch("cms.scenarios.registry.list_all_scenarios", return_value=canned):
            result1 = services.list_scenarios(user)
        canned2 = [copy.deepcopy(s) for s in CANNED_SCENARIOS]
        with patch("cms.scenarios.registry.list_all_scenarios", return_value=canned2):
            result2 = services.list_scenarios(user)
        # Modify result1
        result1[0]["name"] = "MODIFIED"
        # result2 should not be affected
        assert result2[0]["name"] != "MODIFIED"


class TestGetScenario:
    """Tests for get_scenario() service function."""

    @patch("cms.scenarios.registry.get_scenario_detail", return_value=BASIC_SCENARIO)
    def test_returns_dict(self, _mock_detail):
        """Service returns a dictionary."""
        result = services.get_scenario("basic")
        assert isinstance(result, dict)

    @patch("cms.scenarios.registry.get_scenario_detail", return_value=BASIC_SCENARIO)
    def test_returns_basic_scenario(self, _mock_detail):
        """Service returns basic scenario by ID."""
        result = services.get_scenario("basic")
        assert result["id"] == "basic"

    @patch("cms.scenarios.registry.get_scenario_detail", return_value=AD_ATTACK_LAB_SCENARIO)
    def test_returns_ad_attack_lab_scenario(self, _mock_detail):
        """Service returns ad_attack_lab scenario by ID."""
        result = services.get_scenario("ad_attack_lab")
        assert result["id"] == "ad_attack_lab"

    @patch(
        "cms.scenarios.registry.get_scenario_detail",
        side_effect=ValueError("not found"),
    )
    def test_raises_for_unknown_scenario(self, _mock_detail):
        """Service raises CMSError for unknown scenario ID."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.get_scenario("nonexistent")

    @patch("cms.scenarios.registry.get_scenario_detail", return_value=BASIC_SCENARIO)
    def test_scenario_has_required_fields(self, _mock_detail):
        """Returned scenario has all required fields."""
        result = services.get_scenario("basic")
        assert "id" in result
        assert "name" in result
        assert "description" in result
        assert "enabled" in result
        assert "ngfw" in result
        assert "instances" in result


class TestValidateScenarioRequirements:
    """Tests for validate_scenario_requirements() service function.

    Note: With multi-agent support, OS validation happens at create_range time
    based on get_agent_requirements(), not in validate_scenario_requirements.
    """

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_basic_scenario_accepts_any_os(self, mock_load, agent):
        """Basic scenario accepts agent with any OS (from_agent)."""
        mock_template = Mock()
        mock_template.requires_agent.return_value = True
        mock_load.return_value = mock_template
        # Should not raise
        services.validate_scenario_requirements("basic", agent)

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_ad_attack_lab_accepts_windows_agent(self, mock_load):
        """AD attack lab accepts Windows agent (from_agent)."""
        mock_os = Mock()
        mock_os.slug = "windows"
        mock_agent = Mock()
        mock_agent.os = mock_os

        mock_template = Mock()
        mock_template.requires_agent.return_value = True
        mock_load.return_value = mock_template

        # Should not raise
        services.validate_scenario_requirements("ad_attack_lab", mock_agent)

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_ad_attack_lab_accepts_linux_agent(self, mock_load):
        """AD attack lab accepts Linux agent (from_agent allows any OS)."""
        mock_os = Mock()
        mock_os.slug = "linux-debian"
        mock_agent = Mock()
        mock_agent.os = mock_os

        mock_template = Mock()
        mock_template.requires_agent.return_value = True
        mock_load.return_value = mock_template

        # Should not raise - from_agent accepts any OS
        services.validate_scenario_requirements("ad_attack_lab", mock_agent)

    @patch(
        "cms.scenarios.registry.load_scenario_template",
        side_effect=ValueError("not found"),
    )
    def test_raises_for_unknown_scenario(self, _mock_load, agent):
        """Service raises CMSError for unknown scenario ID."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.validate_scenario_requirements("nonexistent", agent)

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_raises_when_agent_is_none_and_required(self, mock_load):
        """Service raises CMSError when agent is None but required."""
        from cms.exceptions import CMSError

        mock_template = Mock()
        mock_template.requires_agent.return_value = True
        mock_load.return_value = mock_template

        with pytest.raises(CMSError, match="requires an agent"):
            services.validate_scenario_requirements("basic", None)
