"""Tests for engine.services.scenarios module."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.services.scenarios import (
    ScenarioValidationError,
    get_scenario_config,
    validate_launch,
)
from mission_control.models import AgentConfig, OperatingSystem

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(username="other@example.com", email="other@example.com")


@pytest.fixture
def windows_os(db):
    """Get the Windows operating system."""
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def linux_os(db):
    """Get the Linux (Debian/Ubuntu) operating system."""
    return OperatingSystem.objects.get(slug="linux-debian")


@pytest.fixture
def windows_agent(db, user, windows_os):
    """Create a Windows agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Windows Agent",
        s3_key="agents/1/test.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
        sha256_hash="abc123",
    )


@pytest.fixture
def linux_agent(db, user, linux_os):
    """Create a Linux agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=linux_os,
        name="Test Linux Agent",
        s3_key="agents/1/test.sh",
        original_filename="test.sh",
        file_size_bytes=1024,
        sha256_hash="def456",
    )


@pytest.fixture
def deleted_agent(db, user, windows_os):
    """Create a soft-deleted agent."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Deleted Agent",
        s3_key="agents/1/deleted.msi",
        original_filename="deleted.msi",
        file_size_bytes=1024,
        sha256_hash="deleted123",
        deleted_at=timezone.now() - timedelta(days=1),
    )


@pytest.fixture
def other_users_agent(db, other_user, windows_os):
    """Create an agent belonging to a different user."""
    return AgentConfig.objects.create(
        user=other_user,
        os=windows_os,
        name="Other Users Agent",
        s3_key="agents/2/other.msi",
        original_filename="other.msi",
        file_size_bytes=1024,
        sha256_hash="other123",
    )


# -----------------------------------------------------------------------------
# Tests for get_scenario_config
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetScenarioConfig:
    """Tests for get_scenario_config function."""

    def test_basic_scenario_with_linux_agent(self):
        """Basic scenario with linux agent returns kali + ubuntu."""
        config = get_scenario_config("basic", "linux")

        assert len(config) == 2
        assert config[0] == {"role": "attacker", "os_type": "kali"}
        assert config[1] == {"role": "victim", "os_type": "ubuntu"}

    def test_basic_scenario_with_windows_agent(self):
        """Basic scenario with windows agent returns kali + windows."""
        config = get_scenario_config("basic", "windows")

        assert len(config) == 2
        assert config[0] == {"role": "attacker", "os_type": "kali"}
        assert config[1] == {"role": "victim", "os_type": "windows"}

    def test_ad_scenario_config(self):
        """AD Attack Lab returns kali + DC + windows victim with join_domain."""
        config = get_scenario_config("ad_attack_lab", "windows")

        assert len(config) == 3

        # Attacker
        assert config[0] == {"role": "attacker", "os_type": "kali"}

        # DC with domain config
        assert config[1]["role"] == "dc"
        assert config[1]["os_type"] == "windows"
        assert "dc_config" in config[1]
        assert config[1]["dc_config"]["domain_name"] == "shifter.local"
        assert config[1]["dc_config"]["netbios_name"] == "SHIFTER"

        # Victim with domain join
        assert config[2]["role"] == "victim"
        assert config[2]["os_type"] == "windows"
        assert config[2]["join_domain"] is True

    def test_unknown_scenario_returns_basic(self):
        """Unknown scenario defaults to basic scenario config."""
        config = get_scenario_config("nonexistent_scenario", "linux")

        assert len(config) == 2
        assert config[0] == {"role": "attacker", "os_type": "kali"}
        assert config[1] == {"role": "victim", "os_type": "ubuntu"}

    def test_os_matching_is_case_insensitive(self):
        """OS name matching should be case insensitive."""
        # All these should produce Windows victim
        for os_name in ["windows", "Windows", "WINDOWS", "WiNdOwS"]:
            config = get_scenario_config("basic", os_name)
            assert config[1]["os_type"] == "windows", f"Failed for: {os_name}"

    def test_non_windows_os_defaults_to_ubuntu(self):
        """Any non-Windows OS should default to Ubuntu victim."""
        # All these should produce Ubuntu victim
        for os_name in ["linux", "Linux", "ubuntu", "debian", "rhel", "anything_else"]:
            config = get_scenario_config("basic", os_name)
            assert config[1]["os_type"] == "ubuntu", f"Failed for: {os_name}"

    def test_ad_scenario_always_uses_windows_victim_regardless_of_agent_os(self):
        """AD Attack Lab always provisions Windows victim, even if agent_os is Linux.

        This documents the current behavior - AD scenarios ignore the agent_os
        parameter for victim configuration because AD requires Windows.
        """
        config = get_scenario_config("ad_attack_lab", "linux")

        # All three instances should still be configured correctly
        assert len(config) == 3
        assert config[0]["os_type"] == "kali"  # attacker
        assert config[1]["os_type"] == "windows"  # DC is always Windows
        assert config[2]["os_type"] == "windows"  # victim is always Windows for AD

    def test_config_structure_matches_provisioner_contract(self):
        """Verify config structure has all required fields for provisioner.

        The provisioner expects each instance config to have at minimum:
        - role: string identifying the instance role
        - os_type: string matching provisioner's AMI catalog
        """
        config = get_scenario_config("basic", "linux")

        for instance in config:
            assert "role" in instance, "Missing required 'role' field"
            assert "os_type" in instance, "Missing required 'os_type' field"
            assert isinstance(instance["role"], str)
            assert isinstance(instance["os_type"], str)

    def test_ad_dc_config_has_required_fields(self):
        """Verify AD DC instance has all required domain configuration."""
        config = get_scenario_config("ad_attack_lab", "windows")
        dc_instance = config[1]

        assert dc_instance["role"] == "dc"
        assert "dc_config" in dc_instance
        assert "domain_name" in dc_instance["dc_config"]
        assert "netbios_name" in dc_instance["dc_config"]
        # Verify values are non-empty strings
        assert len(dc_instance["dc_config"]["domain_name"]) > 0
        assert len(dc_instance["dc_config"]["netbios_name"]) > 0


# -----------------------------------------------------------------------------
# Tests for validate_launch
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateLaunch:
    """Tests for validate_launch function."""

    def test_rejects_linux_agent_for_ad_scenario(self, user, linux_agent):
        """AD Attack Lab requires Windows agent - Linux should fail."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            validate_launch(user, linux_agent.id, "ad_attack_lab")

        # Verify error message is actionable
        error_msg = str(exc_info.value)
        assert "Windows" in error_msg
        assert "MSI" in error_msg  # Tells user what file type to upload
        assert exc_info.value.status_code == 400

    def test_accepts_windows_agent_for_ad_scenario(self, user, windows_agent):
        """AD Attack Lab accepts Windows agent."""
        agent, dc_agent = validate_launch(user, windows_agent.id, "ad_attack_lab")

        assert agent.id == windows_agent.id
        # DC agent is same as victim agent for AD scenario
        assert dc_agent is not None
        assert dc_agent.id == windows_agent.id

    def test_accepts_any_agent_for_basic_scenario(self, user, linux_agent):
        """Basic scenario accepts any agent type."""
        agent, dc_agent = validate_launch(user, linux_agent.id, "basic")

        assert agent.id == linux_agent.id
        # No DC agent for basic scenario
        assert dc_agent is None

    def test_accepts_windows_agent_for_basic_scenario(self, user, windows_agent):
        """Basic scenario also accepts Windows agent."""
        agent, dc_agent = validate_launch(user, windows_agent.id, "basic")

        assert agent.id == windows_agent.id
        assert dc_agent is None

    def test_rejects_nonexistent_agent(self, user):
        """Nonexistent agent ID raises error."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            validate_launch(user, 99999, "basic")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 404

    def test_rejects_other_users_agent(self, user, other_users_agent):
        """Agent belonging to different user raises error."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            validate_launch(user, other_users_agent.id, "basic")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 404

    def test_rejects_deleted_agent(self, user, deleted_agent):
        """Soft-deleted agent raises error."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            validate_launch(user, deleted_agent.id, "basic")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 404

    def test_returned_agent_has_os_loaded(self, user, windows_agent):
        """Verify OS relationship is loaded (no additional DB query needed).

        The service uses select_related("os") so callers can access
        agent.os without triggering another database query.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        agent, _ = validate_launch(user, windows_agent.id, "basic")

        # Accessing agent.os should NOT trigger a new query
        with CaptureQueriesContext(connection) as context:
            _ = agent.os.slug
            _ = agent.os.name

        assert len(context) == 0, "Accessing agent.os should not trigger DB query"

    def test_returned_agent_properties_match(self, user, windows_agent):
        """Verify returned agent has correct properties accessible."""
        agent, _ = validate_launch(user, windows_agent.id, "basic")

        # Verify we can access all the properties we need
        assert agent.name == "Test Windows Agent"
        assert agent.s3_key == "agents/1/test.msi"
        assert agent.os.slug == "windows"
        assert agent.user_id == user.id

    def test_unknown_scenario_still_validates_agent(self, user, windows_agent):
        """Unknown scenario should still validate agent ownership.

        Even if scenario is not recognized, agent validation should occur.
        """
        agent, dc_agent = validate_launch(user, windows_agent.id, "unknown_scenario")

        # Agent should be valid
        assert agent.id == windows_agent.id
        # Unknown scenario treated like basic - no DC agent
        assert dc_agent is None

    def test_dc_agent_is_same_object_as_agent_for_ad(self, user, windows_agent):
        """For AD scenario, dc_agent should be the exact same object as agent."""
        agent, dc_agent = validate_launch(user, windows_agent.id, "ad_attack_lab")

        # Should be the same object reference
        assert agent is dc_agent


class TestScenarioValidationError:
    """Tests for the ScenarioValidationError exception class."""

    def test_default_status_code_is_400(self):
        """Default status code should be 400 (Bad Request)."""
        error = ScenarioValidationError("Test error")
        assert error.status_code == 400

    def test_custom_status_code(self):
        """Should accept custom status code."""
        error = ScenarioValidationError("Not found", status_code=404)
        assert error.status_code == 404

    def test_message_accessible_via_str(self):
        """Error message should be accessible via str()."""
        error = ScenarioValidationError("Custom message")
        assert str(error) == "Custom message"

    def test_message_accessible_via_args(self):
        """Error message should be accessible via args."""
        error = ScenarioValidationError("Custom message")
        assert error.args[0] == "Custom message"
