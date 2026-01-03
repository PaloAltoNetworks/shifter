"""Tests for scenario hydrator.

The hydrator takes a scenario template + agent info and produces
a fully resolved RangeSpec for Engine consumption.

Responsibilities:
- Resolve os_type "from_agent" to actual OS
- Embed agent details into instances with agent_slot
- Return consistent RangeSpec structure
- Input validation and error handling
"""

import pytest
from django.contrib.auth import get_user_model

from cms.models import AgentConfig, OperatingSystem
from shared.schemas import RangeSpec

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com",
        email="test@example.com",
    )


@pytest.fixture
def windows_agent(user, db):
    """Windows agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Windows Agent",
        os=os,
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        file_size_bytes=5000000,
        sha256_hash="abc123def456",
    )


@pytest.fixture
def linux_agent(user, db):
    """Linux agent for testing."""
    os = OperatingSystem.objects.get(slug="linux-debian")
    return AgentConfig.objects.create(
        user=user,
        name="Linux Agent",
        os=os,
        s3_key="agents/456/agent.deb",
        original_filename="cortex_agent.deb",
        file_size_bytes=3000000,
        sha256_hash="def789ghi012",
    )


@pytest.mark.django_db
class TestHydrateScenario:
    """Tests for hydrate_scenario() function."""

    # --- Basic structure ---

    def test_returns_range_request(self, user, windows_agent):
        """hydrate_scenario returns a RangeSpec."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result, RangeSpec)

    def test_includes_scenario_id(self, user, windows_agent):
        """Result includes scenario_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.scenario_id == "basic"

    def test_includes_user_id(self, user, windows_agent):
        """Result includes user_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.user_id == user.id

    def test_includes_instances_list(self, user, windows_agent):
        """Result includes instances list."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result.instances, list)

    def test_basic_has_two_instances(self, user, windows_agent):
        """Basic scenario has attacker and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert len(result.instances) == 2
        roles = [i.role for i in result.instances]
        assert "attacker" in roles
        assert "victim" in roles

    # --- OS resolution from agent ---

    def test_resolves_from_agent_to_windows(self, user, windows_agent):
        """os_type 'from_agent' resolves to 'windows' for Windows agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.os_type == "windows"

    def test_resolves_from_agent_to_ubuntu(self, user, linux_agent):
        """os_type 'from_agent' resolves to 'ubuntu' for Linux agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, linux_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.os_type == "ubuntu"

    def test_attacker_remains_kali(self, user, windows_agent):
        """Attacker os_type remains 'kali' (not resolved from agent)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.instances if i.role == "attacker")
        assert attacker.os_type == "kali"

    # --- Agent embedding ---

    def test_embeds_agent_in_victim(self, user, windows_agent):
        """Agent details are embedded in victim instance."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent is not None

    def test_agent_has_s3_key(self, user, windows_agent):
        """Embedded agent has s3_key."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.s3_key == "agents/123/agent.msi"

    def test_agent_has_filename(self, user, windows_agent):
        """Embedded agent has filename."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.filename == "cortex_agent.msi"

    def test_agent_has_sha256(self, user, windows_agent):
        """Embedded agent has sha256."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.sha256 == "abc123def456"

    def test_attacker_has_no_agent(self, user, windows_agent):
        """Attacker instance has no agent (no agent_slot)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.instances if i.role == "attacker")
        assert attacker.agent is None

    # --- AD Attack Lab scenario ---

    def test_ad_attack_lab_has_three_instances(self, user, windows_agent):
        """AD attack lab has attacker, dc, and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        assert len(result.instances) == 3
        roles = [i.role for i in result.instances]
        assert "attacker" in roles
        assert "dc" in roles
        assert "victim" in roles

    def test_ad_attack_lab_dc_has_dc_config(self, user, windows_agent):
        """DC instance has dc_config with domain settings."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name is not None
        assert dc.dc_config.netbios_name is not None

    def test_ad_attack_lab_victim_joins_domain(self, user, windows_agent):
        """AD victim has join_domain flag."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.join_domain is True

    def test_ad_attack_lab_victim_has_agent(self, user, windows_agent):
        """AD victim has embedded agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.s3_key == "agents/123/agent.msi"

    def test_ad_attack_lab_dc_has_no_agent(self, user, windows_agent):
        """DC instance has no agent (no agent_slot)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.instances if i.role == "dc")
        assert dc.agent is None

    # --- Error handling ---

    def test_raises_for_unknown_scenario(self, user, windows_agent):
        """Raises CMSError for unknown scenario_id."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match="not found"):
            hydrate_scenario("nonexistent", user.id, windows_agent)

    def test_raises_when_agent_is_none(self, user):
        """Raises CMSError when agent is None."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match=r"agent.*required"):
            hydrate_scenario("basic", user.id, None)

    # --- Model serialization ---

    def test_model_dump_returns_dict(self, user, windows_agent):
        """RangeSpec can be serialized to dict."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["scenario_id"] == "basic"
        assert dumped["user_id"] == user.id


@pytest.mark.django_db
class TestHydrateScenarioLogging:
    """Tests for hydrator logging behavior."""

    def test_logs_debug_on_success(self, user, windows_agent, caplog):
        """Logs debug on successful hydration."""
        import logging

        from cms.scenarios.hydrator import hydrate_scenario

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_scenario("basic", user.id, windows_agent)

        assert "basic" in caplog.text or "hydrat" in caplog.text.lower()

    def test_does_not_log_agent_secrets(self, user, windows_agent, caplog):
        """Does not log agent s3_key or sha256 (could be sensitive)."""
        import logging

        from cms.scenarios.hydrator import hydrate_scenario

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_scenario("basic", user.id, windows_agent)

        # s3_key and sha256 should not appear in logs
        assert "agents/123/agent.msi" not in caplog.text
        assert "abc123def456" not in caplog.text
