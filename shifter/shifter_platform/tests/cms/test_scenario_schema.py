"""Tests for CMS scenario schema Pydantic models.

Tests the Pydantic models used to validate scenario templates:
- DCConfig: domain controller configuration
- InstanceConfig: individual instance definition
- SubnetConfig: subnet definition
- ScenarioTemplate: complete scenario template
"""

import pytest
from pydantic import ValidationError


class TestDCConfig:
    """Tests for DCConfig Pydantic model."""

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

    def test_create_attacker_instance(self):
        """InstanceConfig can be created for attacker role."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Attacker", role="attacker", os_type="kali")
        assert instance.name == "Attacker"
        assert instance.asset_type == "vm_runtime_vm"
        assert instance.role == "attacker"
        assert instance.os_type == "kali"

    def test_create_victim_instance(self):
        """InstanceConfig can be created for victim role."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Victim", role="victim", os_type="windows")
        assert instance.role == "victim"
        assert instance.os_type == "windows"

    def test_create_dc_instance(self):
        """InstanceConfig can be created for dc role."""
        from cms.scenarios.schema import DCConfig, InstanceConfig

        dc_config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        instance = InstanceConfig(
            name="Domain Controller",
            role="dc",
            os_type="windows",
            domain_controller=True,
            dc_config=dc_config,
        )
        assert instance.role == "dc"
        assert instance.domain_controller is True
        assert instance.dc_config.domain_name == "lab.local"

    def test_name_is_required(self):
        """InstanceConfig requires name field."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError):
            InstanceConfig(role="attacker", os_type="kali")

    def test_role_is_required(self):
        """InstanceConfig requires role field."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError):
            InstanceConfig(name="Test", os_type="kali")

    def test_os_type_is_required(self):
        """InstanceConfig requires os_type field."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError):
            InstanceConfig(name="Test", role="attacker")

    def test_xdr_agent_defaults_to_false(self):
        """InstanceConfig xdr_agent defaults to False."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Test", role="attacker", os_type="kali")
        assert instance.xdr_agent is False

    def test_xdr_agent_can_be_true(self):
        """InstanceConfig xdr_agent can be set to True."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Victim", role="victim", os_type="windows", xdr_agent=True)
        assert instance.xdr_agent is True

    def test_domain_controller_defaults_to_false(self):
        """InstanceConfig domain_controller defaults to False."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Test", role="victim", os_type="windows")
        assert instance.domain_controller is False

    def test_join_domain_defaults_to_false(self):
        """InstanceConfig join_domain defaults to False."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Test", role="victim", os_type="windows")
        assert instance.join_domain is False

    def test_dc_config_defaults_to_none(self):
        """InstanceConfig dc_config defaults to None."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Test", role="victim", os_type="windows")
        assert instance.dc_config is None

    def test_os_type_from_agent(self):
        """InstanceConfig os_type can be 'from_agent'."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(name="Victim", role="victim", os_type="from_agent", xdr_agent=True)
        assert instance.os_type == "from_agent"

    def test_create_scenario_pod_instance(self):
        """InstanceConfig can declare a pod-backed lower-fidelity asset."""
        from cms.scenarios.schema import InstanceConfig

        instance = InstanceConfig(
            name="Lower Fidelity Target",
            asset_type="scenario_pod",
            role="victim",
            os_type="ubuntu",
        )
        assert instance.asset_type == "scenario_pod"

    def test_scenario_pod_rejects_windows(self):
        """Pod-backed assets are limited to Linux guest types in Slice 12."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError, match="kali or ubuntu"):
            InstanceConfig(name="Bad Pod", asset_type="scenario_pod", role="victim", os_type="windows")

    def test_scenario_pod_rejects_xdr_agent(self):
        """Pod-backed assets cannot declare XDR installation details."""
        from cms.scenarios.schema import InstanceConfig

        with pytest.raises(ValidationError, match="cannot install XDR"):
            InstanceConfig(
                name="Bad Pod",
                asset_type="scenario_pod",
                role="victim",
                os_type="ubuntu",
                xdr_agent=True,
            )


class TestSubnetConfig:
    """Tests for SubnetConfig Pydantic model."""

    def test_create_basic_subnet(self):
        """SubnetConfig can be created with name and instances."""
        from cms.scenarios.schema import SubnetConfig

        subnet = SubnetConfig(name="core", instances=["Attacker", "Victim"])
        assert subnet.name == "core"
        assert subnet.instances == ["Attacker", "Victim"]
        assert subnet.connected_to == []

    def test_create_subnet_with_connections(self):
        """SubnetConfig can specify connected_to subnets."""
        from cms.scenarios.schema import SubnetConfig

        subnet = SubnetConfig(
            name="dc_network",
            instances=["DC"],
            connected_to=["workstation_network"],
        )
        assert subnet.connected_to == ["workstation_network"]

    def test_instances_cannot_be_empty(self):
        """SubnetConfig instances must not be empty."""
        from cms.scenarios.schema import SubnetConfig

        with pytest.raises(ValidationError):
            SubnetConfig(name="empty", instances=[])


class TestScenarioTemplate:
    """Tests for ScenarioTemplate Pydantic model."""

    def test_create_basic_scenario(self):
        """ScenarioTemplate can be created with basic fields."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="basic",
            name="Basic Range",
            description="A basic attacker-victim range",
            instances=[
                InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
                InstanceConfig(name="Victim", role="victim", os_type="from_agent", xdr_agent=True),
            ],
        )
        assert template.id == "basic"
        assert template.name == "Basic Range"
        assert len(template.instances) == 2

    def test_enabled_defaults_to_true(self):
        """ScenarioTemplate enabled defaults to True."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
        )
        assert template.enabled is True

    def test_ngfw_defaults_to_false(self):
        """ScenarioTemplate ngfw defaults to False."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
        )
        assert template.ngfw is False

    def test_id_is_required(self):
        """ScenarioTemplate requires id field."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                name="Test",
                description="Test",
                instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
            )

    def test_name_is_required(self):
        """ScenarioTemplate requires name field."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                description="Test",
                instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
            )

    def test_description_is_required(self):
        """ScenarioTemplate requires description field."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
            )

    def test_instances_is_required(self):
        """ScenarioTemplate requires instances field."""
        from cms.scenarios.schema import ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                description="Test",
            )

    def test_instances_must_not_be_empty(self):
        """ScenarioTemplate instances must not be empty."""
        from cms.scenarios.schema import ScenarioTemplate

        with pytest.raises(ValidationError):
            ScenarioTemplate(
                id="test",
                name="Test",
                description="Test",
                instances=[],
            )

    def test_to_dict_returns_dict(self):
        """ScenarioTemplate.model_dump() returns a dictionary."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="basic",
            name="Basic Range",
            description="A basic range",
            instances=[InstanceConfig(name="Attacker", role="attacker", os_type="kali")],
        )
        result = template.model_dump()
        assert isinstance(result, dict)
        assert result["id"] == "basic"
        assert result["name"] == "Basic Range"

    def test_ad_attack_lab_scenario(self):
        """ScenarioTemplate can represent AD attack lab with DC."""
        from cms.scenarios.schema import (
            DCConfig,
            InstanceConfig,
            ScenarioTemplate,
        )

        template = ScenarioTemplate(
            id="ad_attack_lab",
            name="AD Attack Lab",
            description="Active Directory attack lab with DC",
            instances=[
                InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
                InstanceConfig(
                    name="Domain Controller",
                    role="dc",
                    os_type="windows",
                    domain_controller=True,
                    dc_config=DCConfig(domain_name="lab.local", netbios_name="LAB"),
                ),
                InstanceConfig(
                    name="Workstation",
                    role="victim",
                    os_type="from_agent",
                    xdr_agent=True,
                    join_domain=True,
                ),
            ],
        )
        assert template.id == "ad_attack_lab"
        assert len(template.instances) == 3

        # Find DC instance
        dc = next(i for i in template.instances if i.role == "dc")
        assert dc.domain_controller is True
        assert dc.dc_config.domain_name == "lab.local"

        # Find victim instance
        victim = next(i for i in template.instances if i.role == "victim")
        assert victim.join_domain is True
        assert victim.xdr_agent is True

    def test_requires_agent_returns_true_when_xdr_agent_present(self):
        """requires_agent() returns True if any instance has xdr_agent=True."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
                InstanceConfig(name="Victim", role="victim", os_type="windows", xdr_agent=True),
            ],
        )
        assert template.requires_agent() is True

    def test_requires_agent_returns_false_when_no_xdr_agent(self):
        """requires_agent() returns False if no instance has xdr_agent=True."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
            ],
        )
        assert template.requires_agent() is False

    def test_get_agent_requirements_from_agent_only(self):
        """get_agent_requirements() returns has_from_agent=True for from_agent instances."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Attacker", role="attacker", os_type="kali"),
                InstanceConfig(name="Victim", role="victim", os_type="from_agent", xdr_agent=True),
            ],
        )
        req = template.get_agent_requirements()
        assert req["has_from_agent"] is True
        assert req["requires_windows"] is False
        assert req["requires_linux"] is False

    def test_get_agent_requirements_windows_required(self):
        """get_agent_requirements() returns requires_windows=True for Windows instances with xdr_agent."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Victim", role="victim", os_type="windows", xdr_agent=True),
            ],
        )
        req = template.get_agent_requirements()
        assert req["requires_windows"] is True
        assert req["requires_linux"] is False
        assert req["has_from_agent"] is False

    def test_get_agent_requirements_linux_required(self):
        """get_agent_requirements() returns requires_linux=True for Linux instances with xdr_agent."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Victim", role="victim", os_type="ubuntu", xdr_agent=True),
            ],
        )
        req = template.get_agent_requirements()
        assert req["requires_windows"] is False
        assert req["requires_linux"] is True
        assert req["has_from_agent"] is False

    def test_get_agent_requirements_multi_os(self):
        """get_agent_requirements() returns both requires_windows and requires_linux when both needed."""
        from cms.scenarios.schema import InstanceConfig, ScenarioTemplate

        template = ScenarioTemplate(
            id="test",
            name="Test",
            description="Test",
            instances=[
                InstanceConfig(name="Windows Victim", role="victim", os_type="windows", xdr_agent=True),
                InstanceConfig(name="Linux Server", role="victim", os_type="ubuntu", xdr_agent=True),
            ],
        )
        req = template.get_agent_requirements()
        assert req["requires_windows"] is True
        assert req["requires_linux"] is True
        assert req["has_from_agent"] is False
