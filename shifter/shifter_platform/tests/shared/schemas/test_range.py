"""Tests for shared range request schemas.

Tests the Pydantic models used for CMS to Engine communication:
- AgentDetails: agent file details for provisioning
- DCConfig: domain controller configuration
- InstanceSpec: single instance specification
- RangeSpec: complete range creation request
"""

import uuid

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

    def test_sha256_defaults_to_empty_string(self):
        """AgentDetails sha256 defaults to empty string when not provided."""
        from shared.schemas.range import AgentDetails

        agent = AgentDetails(s3_key="agents/agent.msi", filename="agent.msi")
        assert agent.sha256 == ""

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
        """InstanceSpec can be created with name, role, and os_type."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        assert spec.name == "attacker-kali"
        assert spec.role == "attacker"
        assert spec.os_type == "kali"

    def test_uuid_defaults_to_none(self):
        """InstanceSpec uuid field defaults to None."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        assert spec.uuid is None

    def test_uuid_accepts_string(self):
        """InstanceSpec uuid accepts string value."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", uuid="abc-123", role="attacker", os_type="kali")
        assert spec.uuid == "abc-123"

    def test_role_is_required(self):
        """InstanceSpec requires role field."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(name="test", os_type="kali")

    def test_os_type_is_required(self):
        """InstanceSpec requires os_type field."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(name="test", role="attacker")

    def test_role_validates_allowed_values(self):
        """InstanceSpec role must be attacker, victim, or dc."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(name="test", role="invalid", os_type="kali")

    def test_os_type_validates_allowed_values(self):
        """InstanceSpec os_type must be kali, ubuntu, or windows."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(name="test", role="attacker", os_type="invalid")

    def test_agent_is_optional(self):
        """InstanceSpec agent field defaults to None."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows")
        assert spec.agent is None

    def test_agent_accepts_agent_details(self):
        """InstanceSpec accepts AgentDetails for agent field."""
        from shared.schemas.range import AgentDetails, InstanceSpec

        agent = AgentDetails(s3_key="agents/agent.msi", filename="agent.msi", sha256="abc123")
        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows", agent=agent)
        assert spec.agent is not None
        assert spec.agent.s3_key == "agents/agent.msi"

    def test_dc_config_is_optional(self):
        """InstanceSpec dc_config field defaults to None."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="dc-windows", role="dc", os_type="windows")
        assert spec.dc_config is None

    def test_dc_config_accepts_dc_config(self):
        """InstanceSpec accepts DCConfig for dc_config field."""
        from shared.schemas.range import DCConfig, InstanceSpec

        dc_config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        spec = InstanceSpec(name="dc-windows", role="dc", os_type="windows", dc_config=dc_config)
        assert spec.dc_config is not None
        assert spec.dc_config.domain_name == "lab.local"

    def test_join_domain_defaults_to_false(self):
        """InstanceSpec join_domain defaults to False."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows")
        assert spec.join_domain is False

    def test_join_domain_can_be_set_true(self):
        """InstanceSpec join_domain can be set to True."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows", join_domain=True)
        assert spec.join_domain is True

    def test_model_dump_returns_dict(self):
        """InstanceSpec.model_dump() returns a dictionary."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        result = spec.model_dump()
        assert isinstance(result, dict)
        assert result["name"] == "attacker-kali"
        assert result["role"] == "attacker"
        assert result["os_type"] == "kali"
        assert result["agent"] is None
        assert result["dc_config"] is None
        assert result["join_domain"] is False

    def test_model_validate_from_dict(self):
        """InstanceSpec.model_validate() creates instance from dict."""
        from shared.schemas.range import InstanceSpec

        data = {
            "name": "victim-ubuntu",
            "role": "victim",
            "os_type": "ubuntu",
            "join_domain": False,
        }
        spec = InstanceSpec.model_validate(data)
        assert spec.name == "victim-ubuntu"
        assert spec.role == "victim"
        assert spec.os_type == "ubuntu"

    def test_model_validate_with_nested_agent(self):
        """InstanceSpec.model_validate() handles nested AgentDetails dict."""
        from shared.schemas.range import InstanceSpec

        data = {
            "name": "victim-windows",
            "role": "victim",
            "os_type": "windows",
            "agent": {
                "s3_key": "agents/agent.msi",
                "filename": "agent.msi",
                "sha256": "abc",
            },
        }
        spec = InstanceSpec.model_validate(data)
        assert spec.agent is not None
        assert spec.agent.s3_key == "agents/agent.msi"


class TestRangeSpec:
    """Tests for RangeSpec Pydantic model.

    RangeSpec uses subnets containing instances. Access all_instances
    property to get flattened list of instances across all subnets.
    """

    def test_import_range_request(self):
        """RangeSpec can be imported from shared.schemas.range."""
        from shared.schemas.range import RangeSpec

        assert RangeSpec is not None

    def test_create_with_required_fields(self):
        """RangeSpec can be created with scenario_id, user_id, and subnets."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        instances = [InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")]
        subnets = [SubnetSpec(name="attack_net", instances=instances)]
        request = RangeSpec(scenario_id="basic-attack", user_id=1, subnets=subnets)
        assert request.scenario_id == "basic-attack"
        assert request.user_id == 1
        assert len(request.subnets) == 1
        assert len(request.all_instances) == 1

    def test_scenario_id_is_required(self):
        """RangeSpec requires scenario_id field."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        instances = [InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")]
        subnets = [SubnetSpec(name="attack_net", instances=instances)]
        with pytest.raises(ValidationError):
            RangeSpec(user_id=1, subnets=subnets)

    def test_user_id_is_required(self):
        """RangeSpec requires user_id field."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        instances = [InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")]
        subnets = [SubnetSpec(name="attack_net", instances=instances)]
        with pytest.raises(ValidationError):
            RangeSpec(scenario_id="basic-attack", subnets=subnets)

    def test_subnets_is_required(self):
        """RangeSpec requires subnets field."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError):
            RangeSpec(scenario_id="basic-attack", user_id=1)

    def test_subnets_must_be_list(self):
        """RangeSpec subnets must be a list."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError):
            RangeSpec(scenario_id="basic-attack", user_id=1, subnets="not a list")

    def test_subnets_can_be_empty(self):
        """RangeSpec accepts empty subnets list."""
        from shared.schemas.range import RangeSpec

        request = RangeSpec(scenario_id="basic-attack", user_id=1, subnets=[])
        assert request.subnets == []
        assert request.all_instances == []

    # ---------------------------------------------------------------------
    # Validators - scenario_id must be non-empty
    # ---------------------------------------------------------------------

    def test_rejects_empty_scenario_id(self):
        """RangeSpec rejects empty scenario_id string."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeSpec(scenario_id="", user_id=1, subnets=[])

    def test_rejects_whitespace_only_scenario_id(self):
        """RangeSpec rejects whitespace-only scenario_id."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeSpec(scenario_id="   ", user_id=1, subnets=[])

    # ---------------------------------------------------------------------
    # Validators - user_id must be positive
    # ---------------------------------------------------------------------

    def test_rejects_zero_user_id(self):
        """RangeSpec rejects zero user_id."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="user_id"):
            RangeSpec(scenario_id="basic", user_id=0, subnets=[])

    def test_rejects_negative_user_id(self):
        """RangeSpec rejects negative user_id."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="user_id"):
            RangeSpec(scenario_id="basic", user_id=-1, subnets=[])

    def test_accepts_positive_user_id(self):
        """RangeSpec accepts positive user_id."""
        from shared.schemas.range import RangeSpec

        request = RangeSpec(scenario_id="basic", user_id=1, subnets=[])
        assert request.user_id == 1

    def test_all_instances_contains_instance_specs(self):
        """RangeSpec all_instances returns flattened InstanceSpec list."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        attacker = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        victim = InstanceSpec(name="victim-windows", role="victim", os_type="windows")
        subnets = [
            SubnetSpec(name="attack_net", instances=[attacker]),
            SubnetSpec(name="target_net", instances=[victim]),
        ]
        request = RangeSpec(scenario_id="basic-attack", user_id=1, subnets=subnets)
        assert len(request.all_instances) == 2
        assert request.all_instances[0].role == "attacker"
        assert request.all_instances[1].role == "victim"

    def test_model_dump_returns_dict(self):
        """RangeSpec.model_dump() returns a dictionary."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        instances = [InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")]
        subnets = [SubnetSpec(name="attack_net", instances=instances)]
        request = RangeSpec(scenario_id="basic-attack", user_id=1, subnets=subnets)
        result = request.model_dump()
        assert isinstance(result, dict)
        assert result["scenario_id"] == "basic-attack"
        assert result["user_id"] == 1
        assert len(result["subnets"]) == 1
        assert len(result["subnets"][0]["instances"]) == 1

    def test_model_validate_from_dict(self):
        """RangeSpec.model_validate() creates instance from dict."""
        from shared.schemas.range import RangeSpec

        data = {
            "scenario_id": "basic-attack",
            "user_id": 1,
            "subnets": [
                {
                    "name": "attack_net",
                    "instances": [{"name": "attacker-kali", "role": "attacker", "os_type": "kali"}],
                }
            ],
        }
        request = RangeSpec.model_validate(data)
        assert request.scenario_id == "basic-attack"
        assert request.user_id == 1
        assert len(request.subnets) == 1
        assert request.all_instances[0].role == "attacker"

    def test_model_validate_with_full_nested_structure(self):
        """RangeSpec.model_validate() handles fully nested dict structure."""
        from shared.schemas.range import RangeSpec

        data = {
            "scenario_id": "advanced-scenario",
            "user_id": 42,
            "subnets": [
                {
                    "name": "attack_net",
                    "instances": [
                        {"name": "attacker-kali", "role": "attacker", "os_type": "kali"},
                    ],
                },
                {
                    "name": "dc_net",
                    "instances": [
                        {
                            "name": "dc-windows",
                            "role": "dc",
                            "os_type": "windows",
                            "dc_config": {
                                "domain_name": "lab.local",
                                "netbios_name": "LAB",
                            },
                        },
                    ],
                },
                {
                    "name": "target_net",
                    "instances": [
                        {
                            "name": "victim-windows",
                            "role": "victim",
                            "os_type": "windows",
                            "agent": {
                                "s3_key": "agents/agent.msi",
                                "filename": "cortex.msi",
                                "sha256": "abc123",
                            },
                            "join_domain": True,
                        },
                    ],
                    "connected_to": ["dc_net"],
                },
            ],
        }
        request = RangeSpec.model_validate(data)
        assert request.scenario_id == "advanced-scenario"
        assert request.user_id == 42
        assert len(request.subnets) == 3
        assert len(request.all_instances) == 3
        # Find victim by role
        victim = next(i for i in request.all_instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.filename == "cortex.msi"
        # Find DC by role
        dc = next(i for i in request.all_instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name == "lab.local"


# =============================================================================
# Projection Tests - RangeContext, InstanceContext, RangeRef
# =============================================================================


class TestInstanceContextBase:
    """Tests for InstanceContextBase - base projection for all instance types."""

    def test_import_instance_context_base(self):
        """InstanceContextBase can be imported from shared.schemas.range."""
        from shared.schemas.range import InstanceContextBase

        assert InstanceContextBase is not None

    def test_create_with_required_fields(self):
        """InstanceContextBase can be created with role and os_type."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="attacker", os_type="kali")
        assert ctx.role == "attacker"
        assert ctx.os_type == "kali"

    def test_uuid_defaults_to_none(self):
        """InstanceContextBase uuid field defaults to None."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="attacker", os_type="kali")
        assert ctx.uuid is None

    def test_uuid_accepts_string(self):
        """InstanceContextBase uuid accepts string value."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(uuid="abc-123", role="attacker", os_type="kali")
        assert ctx.uuid == "abc-123"

    def test_role_is_required(self):
        """InstanceContextBase requires role field."""
        from shared.schemas.range import InstanceContextBase

        with pytest.raises(ValidationError):
            InstanceContextBase(os_type="kali")

    def test_os_type_is_required(self):
        """InstanceContextBase requires os_type field."""
        from shared.schemas.range import InstanceContextBase

        with pytest.raises(ValidationError):
            InstanceContextBase(role="attacker")

    def test_role_validates_allowed_values(self):
        """InstanceContextBase role must be attacker, victim, or dc."""
        from shared.schemas.range import InstanceContextBase

        with pytest.raises(ValidationError):
            InstanceContextBase(role="invalid", os_type="kali")

    def test_os_type_validates_allowed_values(self):
        """InstanceContextBase os_type must be kali, ubuntu, or windows."""
        from shared.schemas.range import InstanceContextBase

        with pytest.raises(ValidationError):
            InstanceContextBase(role="attacker", os_type="invalid")

    def test_join_domain_defaults_to_false(self):
        """InstanceContextBase join_domain defaults to False."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="victim", os_type="windows")
        assert ctx.join_domain is False

    def test_join_domain_can_be_set_true(self):
        """InstanceContextBase join_domain can be set to True."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="victim", os_type="windows", join_domain=True)
        assert ctx.join_domain is True

    def test_instance_context_inherits_from_base(self):
        """InstanceContext inherits from InstanceContextBase."""
        from shared.schemas.range import InstanceContext, InstanceContextBase

        assert issubclass(InstanceContext, InstanceContextBase)


class TestInstanceContext:
    """Tests for InstanceContext Pydantic model (template-safe projection)."""

    def test_import_instance_context(self):
        """InstanceContext can be imported from shared.schemas.range."""
        from shared.schemas.range import InstanceContext

        assert InstanceContext is not None

    def test_create_with_required_fields(self):
        """InstanceContext can be created with role and os_type."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(role="attacker", os_type="kali")
        assert ctx.role == "attacker"
        assert ctx.os_type == "kali"

    def test_uuid_defaults_to_none(self):
        """InstanceContext uuid field defaults to None."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(role="attacker", os_type="kali")
        assert ctx.uuid is None

    def test_uuid_accepts_string(self):
        """InstanceContext uuid accepts string value."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(uuid="abc-123", role="attacker", os_type="kali")
        assert ctx.uuid == "abc-123"

    def test_role_is_required(self):
        """InstanceContext requires role field."""
        from shared.schemas.range import InstanceContext

        with pytest.raises(ValidationError):
            InstanceContext(os_type="kali")

    def test_os_type_is_required(self):
        """InstanceContext requires os_type field."""
        from shared.schemas.range import InstanceContext

        with pytest.raises(ValidationError):
            InstanceContext(role="attacker")

    def test_role_validates_allowed_values(self):
        """InstanceContext role must be attacker, victim, or dc."""
        from shared.schemas.range import InstanceContext

        with pytest.raises(ValidationError):
            InstanceContext(role="invalid", os_type="kali")

    def test_os_type_validates_allowed_values(self):
        """InstanceContext os_type must be kali, ubuntu, or windows."""
        from shared.schemas.range import InstanceContext

        with pytest.raises(ValidationError):
            InstanceContext(role="attacker", os_type="invalid")

    def test_join_domain_defaults_to_false(self):
        """InstanceContext join_domain defaults to False."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(role="victim", os_type="windows")
        assert ctx.join_domain is False

    def test_join_domain_can_be_set_true(self):
        """InstanceContext join_domain can be set to True."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(role="victim", os_type="windows", join_domain=True)
        assert ctx.join_domain is True


class TestRangeContext:
    """Tests for RangeContext Pydantic model (template-safe projection)."""

    # ---------------------------------------------------------------------
    # Happy path - creation with valid data
    # ---------------------------------------------------------------------

    def test_import_range_context(self):
        """RangeContext can be imported from shared.schemas.range."""
        from shared.schemas.range import RangeContext

        assert RangeContext is not None

    def test_create_with_required_fields(self):
        """RangeContext can be created with all required fields."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        request_id = uuid.uuid4()
        ctx = RangeContext(
            request_id=request_id,
            range_id=42,
            scenario_id="basic-attack",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.request_id == request_id
        assert ctx.range_id == 42
        assert ctx.scenario_id == "basic-attack"
        assert ctx.user_id == 1
        assert ctx.status == ResourceStatus.READY
        assert ctx.instances == []

    def test_create_with_instances(self):
        """RangeContext can be created with InstanceContext list."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import InstanceContext, RangeContext

        instances = [
            InstanceContext(role="attacker", os_type="kali"),
            InstanceContext(role="victim", os_type="windows"),
        ]
        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.PROVISIONING,
            instances=instances,
        )
        assert len(ctx.instances) == 2
        assert ctx.instances[0].role == "attacker"
        assert ctx.instances[1].role == "victim"

    # ---------------------------------------------------------------------
    # Input validation - field constraints
    # ---------------------------------------------------------------------

    def test_request_id_is_required(self):
        """RangeContext requires request_id field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError):
            RangeContext(
                scenario_id="basic",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_scenario_id_is_required(self):
        """RangeContext requires scenario_id field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid.uuid4(),
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_user_id_is_required(self):
        """RangeContext requires user_id field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_status_is_required(self):
        """RangeContext requires status field."""
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=1,
                instances=[],
            )

    def test_instances_is_required(self):
        """RangeContext requires instances field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=1,
                status=ResourceStatus.READY,
            )

    # ---------------------------------------------------------------------
    # Validators - scenario_id must be non-empty
    # ---------------------------------------------------------------------

    def test_rejects_empty_scenario_id(self):
        """RangeContext rejects empty scenario_id string."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_rejects_whitespace_only_scenario_id(self):
        """RangeContext rejects whitespace-only scenario_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="   ",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    # ---------------------------------------------------------------------
    # Validators - user_id must be positive
    # ---------------------------------------------------------------------

    def test_rejects_zero_user_id(self):
        """RangeContext rejects zero user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="user_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=0,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_rejects_negative_user_id(self):
        """RangeContext rejects negative user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="user_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=-1,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_accepts_positive_user_id(self):
        """RangeContext accepts positive user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.user_id == 1

    # ---------------------------------------------------------------------
    # Validators - status must be valid ResourceStatus
    # ---------------------------------------------------------------------

    def test_rejects_invalid_status_string(self):
        """RangeContext rejects invalid status string."""
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="status"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=1,
                status="invalid_status",
                instances=[],
            )

    def test_accepts_valid_status_string(self):
        """RangeContext accepts valid status string and converts to enum."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status="ready",
            instances=[],
        )
        assert ctx.status == ResourceStatus.READY

    def test_accepts_status_enum_value(self):
        """RangeContext accepts ResourceStatus enum directly."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.PROVISIONING,
            instances=[],
        )
        assert ctx.status == ResourceStatus.PROVISIONING

    # ---------------------------------------------------------------------
    # Computed properties
    # ---------------------------------------------------------------------

    def test_is_ready_true_when_status_ready(self):
        """is_ready returns True when status is READY."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.is_ready is True

    def test_is_ready_false_when_status_not_ready(self):
        """is_ready returns False when status is not READY."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        for status in [
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.FAILED,
            ResourceStatus.DESTROYED,
        ]:
            ctx = RangeContext(
                request_id=uuid.uuid4(),
                range_id=1,
                scenario_id="basic",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_ready is False, f"Expected is_ready=False for {status}"

    def test_is_terminal_true_for_destroyed(self):
        """is_terminal returns True when status is DESTROYED."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.DESTROYED,
            instances=[],
        )
        assert ctx.is_terminal is True

    def test_is_terminal_true_for_failed(self):
        """is_terminal returns True when status is FAILED."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.FAILED,
            instances=[],
        )
        assert ctx.is_terminal is True

    def test_is_terminal_false_for_non_terminal_states(self):
        """is_terminal returns False for non-terminal states."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        for status in [
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.READY,
        ]:
            ctx = RangeContext(
                request_id=uuid.uuid4(),
                range_id=1,
                scenario_id="basic",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_terminal is False, f"is_terminal should be False for {status}"

    def test_is_active_true_for_non_terminal_states(self):
        """is_active returns True for non-terminal states."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        for status in [
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.READY,
        ]:
            ctx = RangeContext(
                request_id=uuid.uuid4(),
                range_id=1,
                scenario_id="basic",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_active is True, f"Expected is_active=True for {status}"

    def test_is_active_false_for_terminal_states(self):
        """is_active returns False for terminal states."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        for status in [ResourceStatus.DESTROYED, ResourceStatus.FAILED]:
            ctx = RangeContext(
                request_id=uuid.uuid4(),
                range_id=1,
                scenario_id="basic",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_active is False, f"is_active should be False for {status}"

    # ---------------------------------------------------------------------
    # range_id field - optional, positive integer if provided
    # ---------------------------------------------------------------------

    def test_range_id_is_optional(self):
        """RangeContext allows range_id to be omitted (defaults to None)."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.range_id is None

    def test_range_id_accepts_positive_integer(self):
        """RangeContext accepts positive range_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=42,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.range_id == 42

    def test_range_id_rejects_zero(self):
        """RangeContext rejects zero range_id when explicitly provided."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="range_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                range_id=0,
                scenario_id="basic",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    def test_range_id_rejects_negative(self):
        """RangeContext rejects negative range_id when explicitly provided."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="range_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                range_id=-1,
                scenario_id="basic",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    # ---------------------------------------------------------------------
    # agent_name field - optional string for display
    # ---------------------------------------------------------------------

    def test_agent_name_is_optional(self):
        """RangeContext agent_name defaults to None."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=42,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.agent_name is None

    def test_agent_name_accepts_string(self):
        """RangeContext accepts agent_name string."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=42,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
            agent_name="Cortex XDR Agent",
        )
        assert ctx.agent_name == "Cortex XDR Agent"

    def test_agent_name_accepts_empty_string(self):
        """RangeContext accepts empty agent_name string."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=42,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
            agent_name="",
        )
        assert ctx.agent_name == ""

    # ---------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------

    def test_model_dump_includes_computed_fields(self):
        """model_dump() includes computed fields is_ready, is_terminal, is_active."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=42,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        result = ctx.model_dump()
        assert "is_ready" in result
        assert "is_terminal" in result
        assert "is_active" in result
        assert result["is_ready"] is True
        assert result["is_terminal"] is False
        assert result["is_active"] is True

    def test_model_validate_from_dict(self):
        """model_validate() creates RangeContext from dict."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        request_id = uuid.uuid4()
        data = {
            "request_id": str(request_id),
            "range_id": 42,
            "scenario_id": "basic",
            "user_id": 42,
            "status": "provisioning",
            "instances": [{"role": "attacker", "os_type": "kali"}],
        }
        ctx = RangeContext.model_validate(data)
        assert ctx.request_id == request_id
        assert ctx.range_id == 42
        assert ctx.scenario_id == "basic"
        assert ctx.user_id == 42
        assert ctx.status == ResourceStatus.PROVISIONING
        assert len(ctx.instances) == 1


class TestRangeRef:
    """Tests for RangeRef Pydantic model (minimal reference projection)."""

    # ---------------------------------------------------------------------
    # Happy path - creation with valid data
    # ---------------------------------------------------------------------

    def test_import_range_ref(self):
        """RangeRef can be imported from shared.schemas.range."""
        from shared.schemas.range import RangeRef

        assert RangeRef is not None

    def test_create_with_required_fields(self):
        """RangeRef can be created with all required fields."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        request_id = uuid.uuid4()
        ref = RangeRef(
            request_id=request_id,
            range_id=123,
            user_id=42,
            status=ResourceStatus.READY,
        )
        assert ref.request_id == request_id
        assert ref.range_id == 123
        assert ref.user_id == 42
        assert ref.status == ResourceStatus.READY

    # ---------------------------------------------------------------------
    # Input validation - field requirements
    # ---------------------------------------------------------------------

    def test_request_id_is_required(self):
        """RangeRef requires request_id field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError):
            RangeRef(user_id=42, status=ResourceStatus.READY)

    def test_range_id_is_optional(self):
        """RangeRef allows range_id to be omitted (defaults to None)."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        ref = RangeRef(
            request_id=uuid.uuid4(),
            user_id=42,
            status=ResourceStatus.READY,
        )
        assert ref.range_id is None

    def test_user_id_is_required(self):
        """RangeRef requires user_id field."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError):
            RangeRef(request_id=uuid.uuid4(), range_id=123, status=ResourceStatus.READY)

    def test_status_is_required(self):
        """RangeRef requires status field."""
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError):
            RangeRef(request_id=uuid.uuid4(), range_id=123, user_id=42)

    # ---------------------------------------------------------------------
    # Validators - range_id must be positive if provided
    # ---------------------------------------------------------------------

    def test_rejects_zero_range_id(self):
        """RangeRef rejects zero range_id when explicitly provided."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="range_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=0,
                user_id=42,
                status=ResourceStatus.READY,
            )

    def test_rejects_negative_range_id(self):
        """RangeRef rejects negative range_id when explicitly provided."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="range_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=-1,
                user_id=42,
                status=ResourceStatus.READY,
            )

    # ---------------------------------------------------------------------
    # Validators - user_id must be positive
    # ---------------------------------------------------------------------

    def test_rejects_zero_user_id(self):
        """RangeRef rejects zero user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="user_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=123,
                user_id=0,
                status=ResourceStatus.READY,
            )

    def test_rejects_negative_user_id(self):
        """RangeRef rejects negative user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="user_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=123,
                user_id=-1,
                status=ResourceStatus.READY,
            )

    # ---------------------------------------------------------------------
    # Validators - status must be valid ResourceStatus
    # ---------------------------------------------------------------------

    def test_rejects_invalid_status_string(self):
        """RangeRef rejects invalid status string."""
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="status"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=123,
                user_id=42,
                status="invalid_status",
            )

    def test_accepts_valid_status_string(self):
        """RangeRef accepts valid status string and converts to enum."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        ref = RangeRef(
            request_id=uuid.uuid4(),
            range_id=123,
            user_id=42,
            status="ready",
        )
        assert ref.status == ResourceStatus.READY

    # ---------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------

    def test_model_dump_returns_dict(self):
        """model_dump() returns a dictionary."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        request_id = uuid.uuid4()
        ref = RangeRef(
            request_id=request_id,
            range_id=123,
            user_id=42,
            status=ResourceStatus.READY,
        )
        result = ref.model_dump()
        assert isinstance(result, dict)
        assert result["request_id"] == request_id
        assert result["range_id"] == 123
        assert result["user_id"] == 42
        assert result["status"] == ResourceStatus.READY

    def test_model_validate_from_dict(self):
        """model_validate() creates RangeRef from dict."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        request_id = uuid.uuid4()
        data = {
            "request_id": str(request_id),
            "range_id": 123,
            "user_id": 42,
            "status": "provisioning",
        }
        ref = RangeRef.model_validate(data)
        assert ref.request_id == request_id
        assert ref.range_id == 123
        assert ref.user_id == 42
        assert ref.status == ResourceStatus.PROVISIONING
