"""Tests for scenario hydrator.

The hydrator takes a scenario template + agent info and produces
a fully resolved RangeSpec for Engine consumption.

Responsibilities:
- Resolve os_type "from_agent" to actual OS
- Embed agent details into instances with agent_slot
- Return consistent RangeSpec structure
- Input validation and error handling
"""

from unittest.mock import Mock, patch

import pytest

from cms.scenarios.schema import DCConfig, InstanceConfig, ScenarioTemplate
from shared.schemas import RangeSpec


def _make_mock_agent(*, os_slug, s3_key, original_filename, sha256_hash):
    """Create a mock agent with the attributes the hydrator accesses."""
    mock_os = Mock()
    mock_os.slug = os_slug
    agent = Mock()
    agent.os = mock_os
    agent.s3_key = s3_key
    agent.original_filename = original_filename
    agent.sha256_hash = sha256_hash
    return agent


# --- Canned templates (pure Pydantic, no DB) ---

BASIC_TEMPLATE = ScenarioTemplate(
    id="basic",
    name="Basic Scenario",
    description="Basic attacker/victim scenario",
    instances=[
        InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
        InstanceConfig(name="Victim", role="victim", os_type="from_agent", xdr_agent=True),
    ],
)

MIXED_ASSET_TEMPLATE = ScenarioTemplate(
    id="mixed_assets",
    name="Mixed Assets",
    description="One VM Runtime asset and one lower-fidelity scenario Pod",
    instances=[
        InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
        InstanceConfig(
            name="Lower Fidelity Target",
            asset_type="scenario_pod",
            role="victim",
            os_type="ubuntu",
        ),
    ],
)

AD_ATTACK_LAB_TEMPLATE = ScenarioTemplate(
    id="ad_attack_lab",
    name="AD Attack Lab",
    description="Active Directory attack scenario",
    instances=[
        InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
        InstanceConfig(
            name="DC",
            role="dc",
            os_type="windows",
            xdr_agent=True,
            domain_controller=True,
            dc_config=DCConfig(domain_name="lab.local", netbios_name="LAB"),
        ),
        InstanceConfig(
            name="Victim",
            role="victim",
            os_type="from_agent",
            xdr_agent=True,
            join_domain=True,
        ),
    ],
)


@pytest.fixture
def user():
    mock = Mock()
    mock.pk = 42
    mock.id = 42
    mock.email = "test@example.com"
    return mock


@pytest.fixture
def windows_agent_obj():
    """Windows agent mock for testing."""
    return _make_mock_agent(
        os_slug="windows",
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        sha256_hash="abc123def456",
    )


@pytest.fixture
def linux_agent_obj():
    """Linux agent mock for testing."""
    return _make_mock_agent(
        os_slug="linux-debian",
        s3_key="agents/456/agent.deb",
        original_filename="cortex_agent.deb",
        sha256_hash="def789ghi012",
    )


@pytest.fixture
def windows_agent(windows_agent_obj):
    """Windows agent dict for hydrator (new format)."""
    return {"windows": windows_agent_obj}


@pytest.fixture
def linux_agent(linux_agent_obj):
    """Linux agent dict for hydrator (new format)."""
    return {"linux": linux_agent_obj}


def _load_scenario_side_effect(scenario_id):
    """Return canned template or raise ValueError."""
    templates = {
        "basic": BASIC_TEMPLATE,
        "ad_attack_lab": AD_ATTACK_LAB_TEMPLATE,
        "mixed_assets": MIXED_ASSET_TEMPLATE,
    }
    if scenario_id not in templates:
        raise ValueError(f"Scenario '{scenario_id}' not found")
    return templates[scenario_id]


class TestHydrateScenario:
    """Tests for hydrate_scenario() function."""

    # --- Basic structure ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_returns_range_request(self, _mock_load, user, windows_agent):
        """hydrate_scenario returns a RangeSpec."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result, RangeSpec)

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_includes_scenario_id(self, _mock_load, user, windows_agent):
        """Result includes scenario_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.scenario_id == "basic"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_includes_user_id(self, _mock_load, user, windows_agent):
        """Result includes user_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.user_id == user.id

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_includes_instances_list(self, _mock_load, user, windows_agent):
        """Result includes all_instances list (flattened from subnets)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result.all_instances, list)

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_basic_has_two_instances(self, _mock_load, user, windows_agent):
        """Basic scenario has attacker and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert len(result.all_instances) == 2
        roles = [i.role for i in result.all_instances]
        assert "attacker" in roles
        assert "victim" in roles

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_preserves_asset_type_from_template(self, _mock_load, user, windows_agent):
        """Hydration keeps pod-backed vs VM-backed asset intent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("mixed_assets", user.id, windows_agent)
        attacker = next(i for i in result.all_instances if i.name == "Attacker")
        pod_target = next(i for i in result.all_instances if i.name == "Lower Fidelity Target")
        assert attacker.asset_type == "vm_runtime_vm"
        assert pod_target.asset_type == "scenario_pod"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_each_instance_has_uuid(self, _mock_load, user, windows_agent):
        """Each instance gets a unique UUID."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        uuids = [i.uuid for i in result.all_instances]
        assert all(uuid is not None for uuid in uuids)
        assert len(set(uuids)) == len(uuids)  # All unique

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_uuid_is_valid_format(self, _mock_load, user, windows_agent):
        """Instance UUIDs are valid UUID4 format."""
        import uuid

        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        for instance in result.all_instances:
            # Will raise ValueError if not valid UUID
            parsed = uuid.UUID(instance.uuid)
            assert parsed.version == 4

    # --- OS resolution from agent ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_resolves_from_agent_to_windows(self, _mock_load, user, windows_agent):
        """os_type 'from_agent' resolves to 'windows' for Windows agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.os_type == "windows"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_resolves_from_agent_to_ubuntu(self, _mock_load, user, linux_agent):
        """os_type 'from_agent' resolves to 'ubuntu' for Linux agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, linux_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.os_type == "ubuntu"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_attacker_remains_kali(self, _mock_load, user, windows_agent):
        """Attacker os_type remains 'kali' (not resolved from agent)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.all_instances if i.role == "attacker")
        assert attacker.os_type == "kali"

    # --- Agent embedding ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_embeds_agent_in_victim(self, _mock_load, user, windows_agent):
        """Agent details are embedded in victim instance."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent is not None

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_agent_has_s3_key(self, _mock_load, user, windows_agent):
        """Embedded agent has s3_key."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent.s3_key == "agents/123/agent.msi"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_agent_has_filename(self, _mock_load, user, windows_agent):
        """Embedded agent has filename."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent.filename == "cortex_agent.msi"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_agent_has_sha256(self, _mock_load, user, windows_agent):
        """Embedded agent has sha256."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent.sha256 == "abc123def456"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_attacker_has_no_agent(self, _mock_load, user, windows_agent):
        """Attacker instance has no agent (no agent_slot)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.all_instances if i.role == "attacker")
        assert attacker.agent is None

    # --- AD Attack Lab scenario ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_ad_attack_lab_has_three_instances(self, _mock_load, user, windows_agent):
        """AD attack lab has attacker, dc, and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        assert len(result.all_instances) == 3
        roles = [i.role for i in result.all_instances]
        assert "attacker" in roles
        assert "dc" in roles
        assert "victim" in roles

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_ad_attack_lab_dc_has_dc_config(self, _mock_load, user, windows_agent):
        """DC instance has dc_config with domain settings."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.all_instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name is not None
        assert dc.dc_config.netbios_name is not None

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_ad_attack_lab_victim_joins_domain(self, _mock_load, user, windows_agent):
        """AD victim has join_domain flag."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.join_domain is True

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_ad_attack_lab_victim_has_agent(self, _mock_load, user, windows_agent):
        """AD victim has embedded agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.s3_key == "agents/123/agent.msi"

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_ad_attack_lab_dc_has_agent(self, _mock_load, user, windows_agent):
        """DC instance has Windows agent (xdr_agent=true in template)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.all_instances if i.role == "dc")
        assert dc.agent is not None
        assert dc.agent.s3_key == windows_agent["windows"].s3_key

    # --- Error handling ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_raises_for_unknown_scenario(self, _mock_load, user, windows_agent):
        """Raises CMSError for unknown scenario_id."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match="not found"):
            hydrate_scenario("nonexistent", user.id, windows_agent)

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_raises_when_agents_empty(self, _mock_load, user):
        """Raises CMSError when agents dict is empty."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match=r"requires an agent"):
            hydrate_scenario("basic", user.id, {})

    # --- Model serialization ---

    @patch("cms.scenarios.hydrator.load_scenario", side_effect=_load_scenario_side_effect)
    def test_model_dump_returns_dict(self, _mock_load, user, windows_agent):
        """RangeSpec can be serialized to dict."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["scenario_id"] == "basic"
        assert dumped["user_id"] == user.id
