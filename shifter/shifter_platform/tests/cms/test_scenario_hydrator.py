"""Behavior tests for the scenario hydrator.

The hydrator takes a scenario template + agent info and produces a fully resolved
RangeSpec for Engine consumption. These tests drive the real
``hydrate_scenario`` against real DB ``Scenario`` rows (loaded through the real
``cms.scenarios.registry.load_scenario_template``) and real ``AgentConfig`` rows,
instead of patching ``cms.scenarios.hydrator.load_scenario`` with canned
templates. The scenario definitions are crafted to exercise the hydrator's
``from_agent`` OS resolution and agent embedding (``xdr_agent=True``), which the
real loader carries through.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

from cms.exceptions import CMSError
from cms.scenarios.hydrator import hydrate_scenario
from shared.schemas import RangeSpec

pytestmark = pytest.mark.django_db

User = get_user_model()

BASIC_DEF = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Victim", "role": "victim", "os_type": "from_agent", "xdr_agent": True},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Victim"]}],
    "ngfw": False,
}

# Mirrors the shipped `basic.yaml`: the victim derives its OS from the
# user-provided agent (`from_agent`) but is authored with `xdr_agent: false`.
# Regression for the launch 400 where this combination left os_type unresolved.
BASIC_NO_XDR_DEF = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Victim", "role": "victim", "os_type": "from_agent", "xdr_agent": False},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Victim"]}],
    "ngfw": False,
}

AD_DEF = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {
            "name": "DC",
            "role": "dc",
            "os_type": "windows",
            "xdr_agent": True,
            "domain_controller": True,
            "dc_config": {"domain_name": "lab.local", "netbios_name": "LAB"},
        },
        {"name": "Victim", "role": "victim", "os_type": "from_agent", "xdr_agent": True, "join_domain": True},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "DC", "Victim"]}],
    "ngfw": False,
}


def _db_scenario(scenario_id, definition):
    from cms.models import Scenario

    staff = User.objects.create_user(
        username=f"hyd-author-{scenario_id}@e.com", email=f"hyd-author-{scenario_id}@e.com", is_staff=True
    )
    return Scenario.objects.create(
        scenario_id=scenario_id,
        name=scenario_id,
        description="Hydrator behavior-test scenario",
        definition=definition,
        created_by=staff,
        updated_by=staff,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(username="hydrator@example.com", email="hydrator@example.com")


@pytest.fixture
def basic_scenario(db):
    return _db_scenario("hydrator-basic", BASIC_DEF)


@pytest.fixture
def basic_no_xdr_scenario(db):
    return _db_scenario("hydrator-basic-no-xdr", BASIC_NO_XDR_DEF)


@pytest.fixture
def ad_scenario(db):
    return _db_scenario("hydrator-ad", AD_DEF)


@pytest.fixture
def windows_agent(user, make_agent):
    """Real Windows AgentConfig keyed for the hydrator."""
    return {"windows": make_agent(user)}


@pytest.fixture
def linux_agent(user, make_agent, db):
    from cms.models import OperatingSystem

    linux_os, _ = OperatingSystem.objects.get_or_create(
        slug="linux-debian", defaults={"name": "Linux (Debian/Ubuntu)", "extensions": [".deb"]}
    )
    return {"linux": make_agent(user, os=linux_os, name="Linux Agent")}


class TestHydrateScenarioStructure:
    def test_returns_range_spec(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        assert isinstance(result, RangeSpec)

    def test_includes_scenario_id(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        assert result.scenario_id == basic_scenario.scenario_id

    def test_includes_user_id(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        assert result.user_id == user.id

    def test_includes_instances_list(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        assert isinstance(result.all_instances, list)

    def test_basic_has_two_instances(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        assert len(result.all_instances) == 2
        assert {i.role for i in result.all_instances} == {"attacker", "victim"}

    def test_each_instance_has_unique_uuid(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        uuids = [i.uuid for i in result.all_instances]
        assert all(u is not None for u in uuids)
        assert len(set(uuids)) == len(uuids)

    def test_uuid_is_valid_uuid4(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        for instance in result.all_instances:
            assert uuid.UUID(instance.uuid).version == 4


class TestHydrateScenarioOsResolution:
    def test_resolves_from_agent_to_windows(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.os_type == "windows"

    def test_resolves_from_agent_to_ubuntu(self, user, basic_scenario, linux_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, linux_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.os_type == "ubuntu"

    def test_attacker_remains_kali(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        attacker = next(i for i in result.all_instances if i.role == "attacker")
        assert attacker.os_type == "kali"

    def test_resolves_from_agent_when_xdr_agent_false(self, user, basic_no_xdr_scenario, windows_agent):
        """A `from_agent` victim resolves and embeds the agent even with xdr_agent=False.

        Regression: the shipped `basic` victim is `from_agent` + `xdr_agent: false`;
        resolution previously short-circuited on `not xdr_agent` and left os_type as
        the literal "from_agent", failing InstanceSpec validation with a 400.
        """
        result = hydrate_scenario(basic_no_xdr_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.os_type == "windows"
        assert victim.agent is not None
        assert victim.agent.s3_key == windows_agent["windows"].s3_key


class TestHydrateScenarioAgentEmbedding:
    def test_embeds_agent_in_victim(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent is not None

    def test_agent_carries_real_file_details(self, user, basic_scenario, windows_agent):
        agent = windows_agent["windows"]
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent.s3_key == agent.s3_key
        assert victim.agent.filename == agent.original_filename
        assert victim.agent.sha256 == agent.sha256_hash

    def test_attacker_has_no_agent(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        attacker = next(i for i in result.all_instances if i.role == "attacker")
        assert attacker.agent is None


class TestHydrateAdAttackLab:
    def test_has_three_instances(self, user, ad_scenario, windows_agent):
        result = hydrate_scenario(ad_scenario.scenario_id, user.id, windows_agent)
        assert {i.role for i in result.all_instances} == {"attacker", "dc", "victim"}

    def test_dc_has_dc_config(self, user, ad_scenario, windows_agent):
        result = hydrate_scenario(ad_scenario.scenario_id, user.id, windows_agent)
        dc = next(i for i in result.all_instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name == "lab.local"
        assert dc.dc_config.netbios_name == "LAB"

    def test_victim_joins_domain(self, user, ad_scenario, windows_agent):
        result = hydrate_scenario(ad_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.join_domain is True

    def test_victim_has_agent(self, user, ad_scenario, windows_agent):
        result = hydrate_scenario(ad_scenario.scenario_id, user.id, windows_agent)
        victim = next(i for i in result.all_instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.s3_key == windows_agent["windows"].s3_key

    def test_dc_has_windows_agent(self, user, ad_scenario, windows_agent):
        result = hydrate_scenario(ad_scenario.scenario_id, user.id, windows_agent)
        dc = next(i for i in result.all_instances if i.role == "dc")
        assert dc.agent is not None
        assert dc.agent.s3_key == windows_agent["windows"].s3_key


class TestHydrateScenarioErrors:
    def test_raises_for_unknown_scenario(self, user, windows_agent):
        with pytest.raises(CMSError, match="not found"):
            hydrate_scenario("nonexistent-scenario", user.id, windows_agent)

    def test_raises_when_agents_empty(self, user, basic_scenario):
        with pytest.raises(CMSError, match="requires an agent"):
            hydrate_scenario(basic_scenario.scenario_id, user.id, {})


class TestHydrateScenarioSerialization:
    def test_model_dump_returns_dict(self, user, basic_scenario, windows_agent):
        result = hydrate_scenario(basic_scenario.scenario_id, user.id, windows_agent)
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["scenario_id"] == basic_scenario.scenario_id
        assert dumped["user_id"] == user.id
