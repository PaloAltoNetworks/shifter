"""Tests for CMS scenario schema Pydantic models.

Tests the Pydantic models used to validate scenario templates:
- AgentRequirements: agent OS constraint and required flag
- DCConfig: domain controller configuration
- InstanceConfig: individual instance definition
- ScenarioTemplate: complete scenario template
"""

import pytest
from pydantic import ValidationError


class TestAgentRequirements:
    """Tests for AgentRequirements Pydantic model."""

    def test_import_agent_requirements(self):
        """AgentRequirements can be imported from cms.scenarios.schema."""
        from cms.scenarios.schema import AgentRequirements

        assert AgentRequirements is not None

    def test_create_with_required_true(self):
        """AgentRequirements can be created with required=True."""
        from cms.scenarios.schema import AgentRequirements

        req = AgentRequirements(required=True)
        assert req.required is True

    def test_create_with_required_false(self):
        """AgentRequirements can be created with required=False."""
        from cms.scenarios.schema import AgentRequirements

        req = AgentRequirements(required=False)
        assert req.required is False

    def test_os_defaults_to_none(self):
        """AgentRequirements os defaults to None (any OS)."""
        from cms.scenarios.schema import AgentRequirements

        req = AgentRequirements(required=True)
        assert req.os is None

    def test_os_can_be_set_to_windows(self):
        """AgentRequirements os can be set to 'windows'."""
        from cms.scenarios.schema import AgentRequirements

        req = AgentRequirements(required=True, os="windows")
        assert req.os == "windows"

    def test_os_can_be_set_to_linux(self):
        """AgentRequirements os can be set to 'linux'."""
        from cms.scenarios.schema import AgentRequirements

        req = AgentRequirements(required=True, os="linux")
        assert req.os == "linux"

    def test_required_is_required_field(self):
        """AgentRequirements requires 'required' field."""
        from cms.scenarios.schema import AgentRequirements

        with pytest.raises(ValidationError):
            AgentRequirements()


class TestDCConfig:
    """Tests for DCConfig Pydantic model."""

    def test_import_dc_config(self):
        """DCConfig can be imported from cms.scenarios.schema."""
        from cms.scenarios.schema import DCConfig

        assert DCConfig is not None

    def test_create_with_domain_name_and_netbios(self):
        """DCConfig can be created with domain_name and netbios_name."""
        from cms.scenarios.schema import DCConfig

        config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        assert config.domain_name == "lab.local"
        assert config.netbios_name == "LAB"

    def test_domain_name_is_required(self):
        """DCConfig requires domain_name field."""
        from cms.scenarios.schema import DCConfig

        with pytest.raises(ValidationError):
            DCConfig(netbios_name="LAB")

    def test_netbios_name_is_required(self):
        """DCConfig requires netbios_name field."""
        from cms.scenarios.schema import DCConfig

        with pytest.raises(ValidationError):
            DCConfig(domain_name="lab.local")


class TestInstanceConfig:
    """Tests for InstanceConfig Pydantic model."""

    def test_import_instance_config(self):
        """InstanceConfig can be imported from cms.scenarios.schema."""
        from cms.scenarios.schema import InstanceConfig

        assert InstanceConfig is not None

    def test_create_attacker_instance(self):
        """InstanceConfig can be created for attacker role."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="attacker", os_type="kali")
        assert instance.role == "attacker"
        assert instance.os_type == "kali"

    def test_create_victim_instance(self):
        """InstanceConfig can be created for victim role."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="windows")
        assert instance.role == "victim"
        assert instance.os_type == "windows"

    def test_create_dc_instance(self):
        """InstanceConfig can be created for dc role."""
        from cms.scenarios.schema import DCConfig, InstanceConfig

        dc_config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        instance = InstanceConfig(
            role="dc",
            os_type="windows",
            domain_controller=True,
            dc_config=dc_config,
        )
        assert instance.role == "dc"
        assert instance.domain_controller is True
        assert instance.dc_config.domain_name == "lab.local"

    def test_role_is_required(self):
        """InstanceConfig requires role field."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError):
            InstanceConfig(os_type="kali")

    def test_os_type_is_required(self):
        """InstanceConfig requires os_type field."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError):
            InstanceConfig(role="attacker")

    def test_agent_slot_defaults_to_none(self):
        """InstanceConfig agent_slot defaults to None."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="attacker", os_type="kali")
        assert instance.agent_slot is None

    def test_agent_slot_can_be_primary(self):
        """InstanceConfig agent_slot can be 'primary'."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="from_agent", agent_slot="primary")
        assert instance.agent_slot == "primary"

    def test_agent_slot_can_be_secondary(self):
        """InstanceConfig agent_slot can be 'secondary'."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="from_agent", agent_slot="secondary")
        assert instance.agent_slot == "secondary"

    def test_domain_controller_defaults_to_false(self):
        """InstanceConfig domain_controller defaults to False."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="windows")
        assert instance.domain_controller is False

    def test_join_domain_defaults_to_false(self):
        """InstanceConfig join_domain defaults to False."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="windows")
        assert instance.join_domain is False

    def test_dc_config_defaults_to_none(self):
        """InstanceConfig dc_config defaults to None."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="windows")
        assert instance.dc_config is None

    def test_os_type_from_agent(self):
        """InstanceConfig os_type can be 'from_agent'."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(role="victim", os_type="from_agent", agent_slot="primary")
        assert instance.os_type == "from_agent"


class TestScenarioTemplate:
    """Tests for ScenarioTemplate Pydantic model."""

    def test_import_scenario_template(self):
        """ScenarioTemplate can be imported from cms.scenarios.schema."""
        from cms.scenarios.schema import ScenarioTemplate

        assert ScenarioTemplate is not None

    def test_create_basic_scenario(self):
        """ScenarioTemplate can be created with basic fields."""
        from cms.scenarios.schema import AgentRequirements, InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="basic",
            name="Basic Range",
            description="A basic attacker-victim range",
            requirements=AgentRequirements(required=True),
            instances=[
                InstanceConfig(role="attacker", os_type="kali"),
                InstanceConfig(role="victim", os_type="from_agent", agent_slot="primary"),
            ],
        )
        assert template.id == "basic"
        assert template.name == "Basic Range"
        assert len(template.instances) == 2

    def test_id_is_required(self):
        """ScenarioTemplate requires id field."""
        from cms.scenarios.schema import AgentRequirements, InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                name="Test",
                description="Test",
                requirements=AgentRequirements(required=True),
                instances=[InstanceConfig(role="attacker", os_type="kali")],
            )

    def test_name_is_required(self):
        """ScenarioTemplate requires name field."""
        from cms.scenarios.schema import AgentRequirements, InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                description="Test",
                requirements=AgentRequirements(required=True),
                instances=[InstanceConfig(role="attacker", os_type="kali")],
            )

    def test_description_is_required(self):
        """ScenarioTemplate requires description field."""
        from cms.scenarios.schema import AgentRequirements, InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                requirements=AgentRequirements(required=True),
                instances=[InstanceConfig(role="attacker", os_type="kali")],
            )

    def test_requirements_is_required(self):
        """ScenarioTemplate requires requirements field."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                description="Test",
                instances=[InstanceConfig(role="attacker", os_type="kali")],
            )

    def test_instances_is_required(self):
        """ScenarioTemplate requires instances field."""
        from cms.scenarios.schema import AgentRequirements, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                description="Test",
                requirements=AgentRequirements(required=True),
            )

    def test_instances_must_not_be_empty(self):
        """ScenarioTemplate instances must not be empty."""
        from cms.scenarios.schema import AgentRequirements, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                description="Test",
                requirements=AgentRequirements(required=True),
                instances=[],
            )

    def test_to_dict_returns_dict(self):
        """ScenarioTemplate.model_dump() returns a dictionary."""
        from cms.scenarios.schema import AgentRequirements, InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="basic",
            name="Basic Range",
            description="A basic range",
            requirements=AgentRequirements(required=True),
            instances=[InstanceConfig(role="attacker", os_type="kali")],
        )
        result = template.model_dump()
        assert isinstance(result, dict)
        assert result["id"] == "basic"
        assert result["name"] == "Basic Range"

    def test_ad_attack_lab_scenario(self):
        """ScenarioTemplate can represent AD attack lab with DC."""
        from cms.scenarios.schema import (
            AgentRequirements,
            DCConfig,
            InstanceConfig,
            ScenarioTemplate,
        )

        template = ScenarioTemplate(
            id="ad_attack_lab",
            name="AD Attack Lab",
            description="Active Directory attack lab with DC",
            requirements=AgentRequirements(required=True, os="windows"),
            instances=[
                InstanceConfig(role="attacker", os_type="kali"),
                InstanceConfig(
                    role="dc",
                    os_type="windows",
                    domain_controller=True,
                    dc_config=DCConfig(domain_name="lab.local", netbios_name="LAB"),
                ),
                InstanceConfig(
                    role="victim",
                    os_type="from_agent",
                    agent_slot="primary",
                    join_domain=True,
                ),
            ],
        )
        assert template.id == "ad_attack_lab"
        assert template.requirements.os == "windows"
        assert len(template.instances) == 3

        # Find DC instance
        dc = next(i for i in template.instances if i.role == "dc")
        assert dc.domain_controller is True
        assert dc.dc_config.domain_name == "lab.local"

        # Find victim instance
        victim = next(i for i in template.instances if i.role == "victim")
        assert victim.join_domain is True
        assert victim.agent_slot == "primary"
