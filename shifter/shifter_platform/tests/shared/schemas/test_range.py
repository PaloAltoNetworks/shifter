"""Tests for shared range request schemas.

Tests the Pydantic models used for CMS to Engine communication:
- AgentDetails: agent file details for provisioning
- DCConfig: domain controller configuration
- InstanceSpec: single instance specification
- RangeRequest: complete range creation request
"""

import pytest
from pydantic import ValidationError


class TestAgentDetails:
    """Tests for AgentDetails Pydantic model."""

    def test_import_agent_details(self):
        """AgentDetails can be imported from shared.schemas.range."""
        from shared.schemas.range import AgentDetails

        assert AgentDetails is not None

    def test_create_with_all_required_fields(self):
        """AgentDetails can be created with all required fields."""
        from shared.schemas.range import AgentDetails

        agent = AgentDetails(
            s3_key="agents/user_1/agent.msi",
            filename="cortex_agent.msi",
            sha256="abc123def456",
        )
        assert agent.s3_key == "agents/user_1/agent.msi"
        assert agent.filename == "cortex_agent.msi"
        assert agent.sha256 == "abc123def456"

    def test_s3_key_is_required(self):
        """AgentDetails requires s3_key field."""
        from shared.schemas.range import AgentDetails

        with pytest.raises(ValidationError):
            AgentDetails(filename="agent.msi", sha256="abc123")

    def test_filename_is_required(self):
        """AgentDetails requires filename field."""
        from shared.schemas.range import AgentDetails

        with pytest.raises(ValidationError):
            AgentDetails(s3_key="agents/agent.msi", sha256="abc123")

    def test_sha256_is_required(self):
        """AgentDetails requires sha256 field."""
        from shared.schemas.range import AgentDetails

        with pytest.raises(ValidationError):
            AgentDetails(s3_key="agents/agent.msi", filename="agent.msi")

    def test_model_dump_returns_dict(self):
        """AgentDetails.model_dump() returns a dictionary."""
        from shared.schemas.range import AgentDetails

        agent = AgentDetails(
            s3_key="agents/agent.msi",
            filename="agent.msi",
            sha256="abc123",
        )
        result = agent.model_dump()
        assert isinstance(result, dict)
        assert result["s3_key"] == "agents/agent.msi"
        assert result["filename"] == "agent.msi"
        assert result["sha256"] == "abc123"

    def test_model_validate_from_dict(self):
        """AgentDetails.model_validate() creates instance from dict."""
        from shared.schemas.range import AgentDetails

        data = {
            "s3_key": "agents/agent.msi",
            "filename": "agent.msi",
            "sha256": "abc123",
        }
        agent = AgentDetails.model_validate(data)
        assert agent.s3_key == "agents/agent.msi"
        assert agent.filename == "agent.msi"
        assert agent.sha256 == "abc123"


class TestDCConfig:
    """Tests for DCConfig Pydantic model."""

    def test_import_dc_config(self):
        """DCConfig can be imported from shared.schemas.range."""
        from shared.schemas.range import DCConfig

        assert DCConfig is not None

    def test_create_with_all_required_fields(self):
        """DCConfig can be created with domain_name and netbios_name."""
        from shared.schemas.range import DCConfig

        config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        assert config.domain_name == "lab.local"
        assert config.netbios_name == "LAB"

    def test_domain_name_is_required(self):
        """DCConfig requires domain_name field."""
        from shared.schemas.range import DCConfig

        with pytest.raises(ValidationError):
            DCConfig(netbios_name="LAB")

    def test_netbios_name_is_required(self):
        """DCConfig requires netbios_name field."""
        from shared.schemas.range import DCConfig

        with pytest.raises(ValidationError):
            DCConfig(domain_name="lab.local")

    def test_model_dump_returns_dict(self):
        """DCConfig.model_dump() returns a dictionary."""
        from shared.schemas.range import DCConfig

        config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        result = config.model_dump()
        assert isinstance(result, dict)
        assert result["domain_name"] == "lab.local"
        assert result["netbios_name"] == "LAB"

    def test_model_validate_from_dict(self):
        """DCConfig.model_validate() creates instance from dict."""
        from shared.schemas.range import DCConfig

        data = {"domain_name": "lab.local", "netbios_name": "LAB"}
        config = DCConfig.model_validate(data)
        assert config.domain_name == "lab.local"
        assert config.netbios_name == "LAB"


class TestInstanceSpec:
    """Tests for InstanceSpec Pydantic model."""

    def test_import_instance_spec(self):
        """InstanceSpec can be imported from shared.schemas.range."""
        from shared.schemas.range import InstanceSpec

        assert InstanceSpec is not None

    def test_create_with_required_fields(self):
        """InstanceSpec can be created with role and os_type."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="attacker", os_type="kali")
        assert spec.role == "attacker"
        assert spec.os_type == "kali"

    def test_role_is_required(self):
        """InstanceSpec requires role field."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(os_type="kali")

    def test_os_type_is_required(self):
        """InstanceSpec requires os_type field."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(role="attacker")

    def test_role_validates_allowed_values(self):
        """InstanceSpec role must be attacker, victim, or dc."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(role="invalid", os_type="kali")

    def test_os_type_validates_allowed_values(self):
        """InstanceSpec os_type must be kali, ubuntu, or windows."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(role="attacker", os_type="invalid")

    def test_agent_is_optional(self):
        """InstanceSpec agent field defaults to None."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="victim", os_type="windows")
        assert spec.agent is None

    def test_agent_accepts_agent_details(self):
        """InstanceSpec accepts AgentDetails for agent field."""
        from shared.schemas.range import AgentDetails, InstanceSpec

        agent = AgentDetails(s3_key="agents/agent.msi", filename="agent.msi", sha256="abc123")
        spec = InstanceSpec(role="victim", os_type="windows", agent=agent)
        assert spec.agent is not None
        assert spec.agent.s3_key == "agents/agent.msi"

    def test_dc_config_is_optional(self):
        """InstanceSpec dc_config field defaults to None."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="dc", os_type="windows")
        assert spec.dc_config is None

    def test_dc_config_accepts_dc_config(self):
        """InstanceSpec accepts DCConfig for dc_config field."""
        from shared.schemas.range import DCConfig, InstanceSpec

        dc_config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        spec = InstanceSpec(role="dc", os_type="windows", dc_config=dc_config)
        assert spec.dc_config is not None
        assert spec.dc_config.domain_name == "lab.local"

    def test_join_domain_defaults_to_false(self):
        """InstanceSpec join_domain defaults to False."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="victim", os_type="windows")
        assert spec.join_domain is False

    def test_join_domain_can_be_set_true(self):
        """InstanceSpec join_domain can be set to True."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="victim", os_type="windows", join_domain=True)
        assert spec.join_domain is True

    def test_model_dump_returns_dict(self):
        """InstanceSpec.model_dump() returns a dictionary."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(role="attacker", os_type="kali")
        result = spec.model_dump()
        assert isinstance(result, dict)
        assert result["role"] == "attacker"
        assert result["os_type"] == "kali"
        assert result["agent"] is None
        assert result["dc_config"] is None
        assert result["join_domain"] is False

    def test_model_validate_from_dict(self):
        """InstanceSpec.model_validate() creates instance from dict."""
        from shared.schemas.range import InstanceSpec

        data = {"role": "victim", "os_type": "ubuntu", "join_domain": False}
        spec = InstanceSpec.model_validate(data)
        assert spec.role == "victim"
        assert spec.os_type == "ubuntu"

    def test_model_validate_with_nested_agent(self):
        """InstanceSpec.model_validate() handles nested AgentDetails dict."""
        from shared.schemas.range import InstanceSpec

        data = {
            "role": "victim",
            "os_type": "windows",
            "agent": {"s3_key": "agents/agent.msi", "filename": "agent.msi", "sha256": "abc"},
        }
        spec = InstanceSpec.model_validate(data)
        assert spec.agent is not None
        assert spec.agent.s3_key == "agents/agent.msi"


class TestRangeRequest:
    """Tests for RangeRequest Pydantic model."""

    def test_import_range_request(self):
        """RangeRequest can be imported from shared.schemas.range."""
        from shared.schemas.range import RangeRequest

        assert RangeRequest is not None

    def test_create_with_required_fields(self):
        """RangeRequest can be created with scenario_id, user_id, and instances."""
        from shared.schemas.range import InstanceSpec, RangeRequest

        instances = [InstanceSpec(role="attacker", os_type="kali")]
        request = RangeRequest(scenario_id="basic-attack", user_id=1, instances=instances)
        assert request.scenario_id == "basic-attack"
        assert request.user_id == 1
        assert len(request.instances) == 1

    def test_scenario_id_is_required(self):
        """RangeRequest requires scenario_id field."""
        from shared.schemas.range import InstanceSpec, RangeRequest

        instances = [InstanceSpec(role="attacker", os_type="kali")]
        with pytest.raises(ValidationError):
            RangeRequest(user_id=1, instances=instances)

    def test_user_id_is_required(self):
        """RangeRequest requires user_id field."""
        from shared.schemas.range import InstanceSpec, RangeRequest

        instances = [InstanceSpec(role="attacker", os_type="kali")]
        with pytest.raises(ValidationError):
            RangeRequest(scenario_id="basic-attack", instances=instances)

    def test_instances_is_required(self):
        """RangeRequest requires instances field."""
        from shared.schemas.range import RangeRequest

        with pytest.raises(ValidationError):
            RangeRequest(scenario_id="basic-attack", user_id=1)

    def test_instances_must_be_list(self):
        """RangeRequest instances must be a list."""
        from shared.schemas.range import RangeRequest

        with pytest.raises(ValidationError):
            RangeRequest(scenario_id="basic-attack", user_id=1, instances="not a list")

    def test_instances_can_be_empty(self):
        """RangeRequest accepts empty instances list."""
        from shared.schemas.range import RangeRequest

        request = RangeRequest(scenario_id="basic-attack", user_id=1, instances=[])
        assert request.instances == []

    def test_instances_contains_instance_specs(self):
        """RangeRequest instances list contains InstanceSpec objects."""
        from shared.schemas.range import InstanceSpec, RangeRequest

        instances = [
            InstanceSpec(role="attacker", os_type="kali"),
            InstanceSpec(role="victim", os_type="windows"),
        ]
        request = RangeRequest(scenario_id="basic-attack", user_id=1, instances=instances)
        assert len(request.instances) == 2
        assert request.instances[0].role == "attacker"
        assert request.instances[1].role == "victim"

    def test_model_dump_returns_dict(self):
        """RangeRequest.model_dump() returns a dictionary."""
        from shared.schemas.range import InstanceSpec, RangeRequest

        instances = [InstanceSpec(role="attacker", os_type="kali")]
        request = RangeRequest(scenario_id="basic-attack", user_id=1, instances=instances)
        result = request.model_dump()
        assert isinstance(result, dict)
        assert result["scenario_id"] == "basic-attack"
        assert result["user_id"] == 1
        assert len(result["instances"]) == 1

    def test_model_validate_from_dict(self):
        """RangeRequest.model_validate() creates instance from dict."""
        from shared.schemas.range import RangeRequest

        data = {
            "scenario_id": "basic-attack",
            "user_id": 1,
            "instances": [{"role": "attacker", "os_type": "kali"}],
        }
        request = RangeRequest.model_validate(data)
        assert request.scenario_id == "basic-attack"
        assert request.user_id == 1
        assert len(request.instances) == 1
        assert request.instances[0].role == "attacker"

    def test_model_validate_with_full_nested_structure(self):
        """RangeRequest.model_validate() handles fully nested dict structure."""
        from shared.schemas.range import RangeRequest

        data = {
            "scenario_id": "advanced-scenario",
            "user_id": 42,
            "instances": [
                {"role": "attacker", "os_type": "kali"},
                {
                    "role": "victim",
                    "os_type": "windows",
                    "agent": {
                        "s3_key": "agents/agent.msi",
                        "filename": "cortex.msi",
                        "sha256": "abc123",
                    },
                    "join_domain": True,
                },
                {
                    "role": "dc",
                    "os_type": "windows",
                    "dc_config": {"domain_name": "lab.local", "netbios_name": "LAB"},
                },
            ],
        }
        request = RangeRequest.model_validate(data)
        assert request.scenario_id == "advanced-scenario"
        assert request.user_id == 42
        assert len(request.instances) == 3
        assert request.instances[1].agent is not None
        assert request.instances[1].agent.filename == "cortex.msi"
        assert request.instances[2].dc_config is not None
        assert request.instances[2].dc_config.domain_name == "lab.local"
