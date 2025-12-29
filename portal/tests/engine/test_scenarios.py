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

        assert "Windows" in str(exc_info.value)
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
