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

# =============================================================================
# Parametrized round-trip tests for simple schema models
# =============================================================================

_ROUND_TRIP_CASES = [
    pytest.param(
        "shared.schemas.range.AgentDetails",
        {"s3_key": "agents/agent.msi", "filename": "agent.msi", "sha256": "abc123"},
        {"s3_key": "agents/agent.msi", "filename": "agent.msi", "sha256": "abc123"},
        id="AgentDetails",
    ),
    pytest.param(
        "shared.schemas.range.DCConfig",
        {"domain_name": "lab.local", "netbios_name": "LAB"},
        {"domain_name": "lab.local", "netbios_name": "LAB"},
        id="DCConfig",
    ),
    pytest.param(
        "shared.schemas.range.InstanceSpec",
        {"name": "attacker-kali", "role": "attacker", "os_type": "kali"},
        {"name": "attacker-kali", "role": "attacker", "os_type": "kali"},
        id="InstanceSpec",
    ),
]


@pytest.mark.parametrize("model_path,kwargs,expected_fields", _ROUND_TRIP_CASES)
class TestSchemaRoundTrip:
    """model_dump/model_validate round-trip for simple range schemas."""

    @staticmethod
    def _import(model_path):
        module_path, class_name = model_path.rsplit(".", 1)
        import importlib

        return getattr(importlib.import_module(module_path), class_name)

    def test_model_dump_returns_dict(self, model_path, kwargs, expected_fields):
        cls = self._import(model_path)
        instance = cls(**kwargs)
        result = instance.model_dump()
        assert isinstance(result, dict)
        for key, value in expected_fields.items():
            assert result[key] == value

    def test_model_validate_round_trip(self, model_path, kwargs, expected_fields):
        cls = self._import(model_path)
        instance = cls.model_validate(kwargs)
        for key, value in expected_fields.items():
            assert getattr(instance, key) == value


class TestAgentDetails:
    """Tests for AgentDetails Pydantic model."""

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

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("s3_key", {"filename": "agent.msi", "sha256": "abc123"}, id="s3_key"),
            pytest.param("filename", {"s3_key": "agents/agent.msi", "sha256": "abc123"}, id="filename"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """AgentDetails requires s3_key and filename fields."""
        from shared.schemas.range import AgentDetails

        with pytest.raises(ValidationError):
            AgentDetails(**kwargs)

    def test_sha256_defaults_to_empty_string(self):
        """AgentDetails sha256 defaults to empty string when not provided."""
        from shared.schemas.range import AgentDetails

        agent = AgentDetails(s3_key="agents/agent.msi", filename="agent.msi")
        assert agent.sha256 == ""


class TestDCConfig:
    """Tests for DCConfig Pydantic model."""

    def test_create_with_all_required_fields(self):
        """DCConfig can be created with domain_name and netbios_name."""
        from shared.schemas.range import DCConfig

        config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        assert config.domain_name == "lab.local"
        assert config.netbios_name == "LAB"

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("domain_name", {"netbios_name": "LAB"}, id="domain_name"),
            pytest.param("netbios_name", {"domain_name": "lab.local"}, id="netbios_name"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """DCConfig requires domain_name and netbios_name fields."""
        from shared.schemas.range import DCConfig

        with pytest.raises(ValidationError):
            DCConfig(**kwargs)


class TestInstanceSpec:
    """Tests for InstanceSpec Pydantic model."""

    def test_create_with_required_fields(self):
        """InstanceSpec can be created with name, role, and os_type."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        assert spec.name == "attacker-kali"
        assert spec.role == "attacker"
        assert spec.os_type == "kali"

    @pytest.mark.parametrize(
        "field,default",
        [
            pytest.param("uuid", None, id="uuid"),
            pytest.param("agent", None, id="agent"),
            pytest.param("dc_config", None, id="dc_config"),
            pytest.param("join_domain", False, id="join_domain"),
        ],
    )
    def test_optional_field_defaults(self, field, default):
        """InstanceSpec optional fields have correct defaults."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")
        assert getattr(spec, field) == default

    def test_uuid_accepts_string(self):
        """InstanceSpec uuid accepts string value."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="attacker-kali", uuid="abc-123", role="attacker", os_type="kali")
        assert spec.uuid == "abc-123"

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("role", {"name": "test", "os_type": "kali"}, id="role"),
            pytest.param("os_type", {"name": "test", "role": "attacker"}, id="os_type"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """InstanceSpec requires role and os_type fields."""
        from shared.schemas.range import InstanceSpec

        with pytest.raises(ValidationError):
            InstanceSpec(**kwargs)

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("role", "invalid", id="invalid-role"),
            pytest.param("os_type", "invalid", id="invalid-os_type"),
        ],
    )
    def test_validates_allowed_values(self, field, value):
        """InstanceSpec validates allowed values for role and os_type."""
        from shared.schemas.range import InstanceSpec

        kwargs = {"name": "test", "role": "attacker", "os_type": "kali"}
        kwargs[field] = value
        with pytest.raises(ValidationError):
            InstanceSpec(**kwargs)

    def test_agent_accepts_agent_details(self):
        """InstanceSpec accepts AgentDetails for agent field."""
        from shared.schemas.range import AgentDetails, InstanceSpec

        agent = AgentDetails(s3_key="agents/agent.msi", filename="agent.msi", sha256="abc123")
        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows", agent=agent)
        assert spec.agent is not None
        assert spec.agent.s3_key == "agents/agent.msi"

    def test_dc_config_accepts_dc_config(self):
        """InstanceSpec accepts DCConfig for dc_config field."""
        from shared.schemas.range import DCConfig, InstanceSpec

        dc_config = DCConfig(domain_name="lab.local", netbios_name="LAB")
        spec = InstanceSpec(name="dc-windows", role="dc", os_type="windows", dc_config=dc_config)
        assert spec.dc_config is not None
        assert spec.dc_config.domain_name == "lab.local"

    def test_join_domain_can_be_set_true(self):
        """InstanceSpec join_domain can be set to True."""
        from shared.schemas.range import InstanceSpec

        spec = InstanceSpec(name="victim-windows", role="victim", os_type="windows", join_domain=True)
        assert spec.join_domain is True

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

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("scenario_id", {"user_id": 1}, id="scenario_id"),
            pytest.param("user_id", {"scenario_id": "basic-attack"}, id="user_id"),
            pytest.param("subnets", {"scenario_id": "basic-attack", "user_id": 1}, id="subnets"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """RangeSpec requires scenario_id, user_id, and subnets."""
        from shared.schemas.range import InstanceSpec, RangeSpec
        from shared.schemas.subnet import SubnetSpec

        # Add subnets if not the missing field
        if missing_field != "subnets" and "subnets" not in kwargs:
            instances = [InstanceSpec(name="attacker-kali", role="attacker", os_type="kali")]
            kwargs["subnets"] = [SubnetSpec(name="attack_net", instances=instances)]

        with pytest.raises(ValidationError):
            RangeSpec(**kwargs)

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
    # Validators
    # ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        "scenario_id",
        [
            pytest.param("", id="empty"),
            pytest.param("   ", id="whitespace-only"),
        ],
    )
    def test_rejects_invalid_scenario_id(self, scenario_id):
        """RangeSpec rejects empty/whitespace scenario_id."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeSpec(scenario_id=scenario_id, user_id=1, subnets=[])

    @pytest.mark.parametrize(
        "user_id",
        [
            pytest.param(0, id="zero"),
            pytest.param(-1, id="negative"),
        ],
    )
    def test_rejects_invalid_user_id(self, user_id):
        """RangeSpec rejects zero/negative user_id."""
        from shared.schemas.range import RangeSpec

        with pytest.raises(ValidationError, match="user_id"):
            RangeSpec(scenario_id="basic", user_id=user_id, subnets=[])

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

    def test_create_with_required_fields(self):
        """InstanceContextBase can be created with role and os_type."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="attacker", os_type="kali")
        assert ctx.role == "attacker"
        assert ctx.os_type == "kali"

    @pytest.mark.parametrize(
        "field,default",
        [
            pytest.param("uuid", None, id="uuid"),
            pytest.param("join_domain", False, id="join_domain"),
        ],
    )
    def test_optional_field_defaults(self, field, default):
        """InstanceContextBase optional fields have correct defaults."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(role="attacker", os_type="kali")
        assert getattr(ctx, field) == default

    def test_uuid_accepts_string(self):
        """InstanceContextBase uuid accepts string value."""
        from shared.schemas.range import InstanceContextBase

        ctx = InstanceContextBase(uuid="abc-123", role="attacker", os_type="kali")
        assert ctx.uuid == "abc-123"

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("role", {"os_type": "kali"}, id="role"),
            pytest.param("os_type", {"role": "attacker"}, id="os_type"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """InstanceContextBase requires role and os_type fields."""
        from shared.schemas.range import InstanceContextBase

        with pytest.raises(ValidationError):
            InstanceContextBase(**kwargs)

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("role", "invalid", id="invalid-role"),
            pytest.param("os_type", "invalid", id="invalid-os_type"),
        ],
    )
    def test_validates_allowed_values(self, field, value):
        """InstanceContextBase validates allowed values for role and os_type."""
        from shared.schemas.range import InstanceContextBase

        kwargs = {"role": "attacker", "os_type": "kali"}
        kwargs[field] = value
        with pytest.raises(ValidationError):
            InstanceContextBase(**kwargs)

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
    """Tests for InstanceContext Pydantic model (template-safe projection).

    InstanceContext inherits from InstanceContextBase. Only tests unique to
    InstanceContext are here; inherited behavior is tested in TestInstanceContextBase.
    """

    def test_create_with_required_fields(self):
        """InstanceContext can be created with role and os_type."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(role="attacker", os_type="kali")
        assert ctx.role == "attacker"
        assert ctx.os_type == "kali"

    def test_uuid_accepts_string(self):
        """InstanceContext uuid accepts string value."""
        from shared.schemas.range import InstanceContext

        ctx = InstanceContext(uuid="abc-123", role="attacker", os_type="kali")
        assert ctx.uuid == "abc-123"


class TestRangeContext:
    """Tests for RangeContext Pydantic model (template-safe projection)."""

    # ---------------------------------------------------------------------
    # Happy path - creation with valid data
    # ---------------------------------------------------------------------

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

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("request_id", {"scenario_id": "basic", "user_id": 1, "instances": []}, id="request_id"),
            pytest.param("scenario_id", {"user_id": 1, "instances": []}, id="scenario_id"),
            pytest.param("user_id", {"scenario_id": "basic", "instances": []}, id="user_id"),
            pytest.param("status", {"scenario_id": "basic", "user_id": 1, "instances": []}, id="status"),
            pytest.param("instances", {"scenario_id": "basic", "user_id": 1}, id="instances"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """RangeContext requires request_id, scenario_id, user_id, status, instances."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        # Add request_id and status if not the missing field
        if missing_field != "request_id" and "request_id" not in kwargs:
            kwargs["request_id"] = uuid.uuid4()
        if missing_field != "status" and "status" not in kwargs:
            kwargs["status"] = ResourceStatus.READY

        with pytest.raises(ValidationError):
            RangeContext(**kwargs)

    # ---------------------------------------------------------------------
    # Validators
    # ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        "scenario_id",
        [pytest.param("", id="empty"), pytest.param("   ", id="whitespace-only")],
    )
    def test_rejects_invalid_scenario_id(self, scenario_id):
        """RangeContext rejects empty/whitespace scenario_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="scenario_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id=scenario_id,
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    @pytest.mark.parametrize("user_id", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")])
    def test_rejects_invalid_user_id(self, user_id):
        """RangeContext rejects zero/negative user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="user_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                scenario_id="basic",
                user_id=user_id,
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

    @pytest.mark.parametrize(
        "status_input,expected_name",
        [
            pytest.param("ready", "READY", id="string"),
            pytest.param("PROVISIONING", "PROVISIONING", id="enum-value"),
        ],
    )
    def test_accepts_valid_status(self, status_input, expected_name):
        """RangeContext accepts valid status string or enum."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        is_enum_name = isinstance(status_input, str) and status_input.isupper()
        status = ResourceStatus[expected_name] if is_enum_name else status_input
        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=status,
            instances=[],
        )
        assert ctx.status == ResourceStatus[expected_name]

    # ---------------------------------------------------------------------
    # Computed properties
    # ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        "status,is_ready,is_terminal,is_active",
        [
            pytest.param("READY", True, False, True, id="ready"),
            pytest.param("PENDING", False, False, True, id="pending"),
            pytest.param("PROVISIONING", False, False, True, id="provisioning"),
            pytest.param("FAILED", False, True, False, id="failed"),
            pytest.param("DESTROYED", False, True, False, id="destroyed"),
        ],
    )
    def test_computed_properties(self, status, is_ready, is_terminal, is_active):
        """Computed properties reflect status correctly."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        ctx = RangeContext(
            request_id=uuid.uuid4(),
            range_id=1,
            scenario_id="basic",
            user_id=1,
            status=ResourceStatus[status],
            instances=[],
        )
        assert ctx.is_ready is is_ready
        assert ctx.is_terminal is is_terminal
        assert ctx.is_active is is_active

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

    @pytest.mark.parametrize("range_id", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")])
    def test_range_id_rejects_invalid(self, range_id):
        """RangeContext rejects zero/negative range_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        with pytest.raises(ValidationError, match="range_id"):
            RangeContext(
                request_id=uuid.uuid4(),
                range_id=range_id,
                scenario_id="basic",
                user_id=1,
                status=ResourceStatus.READY,
                instances=[],
            )

    # ---------------------------------------------------------------------
    # agent_name field - optional string for display
    # ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        "agent_name,expected",
        [
            pytest.param(None, None, id="default-none"),
            pytest.param("Cortex XDR Agent", "Cortex XDR Agent", id="string"),
            pytest.param("", "", id="empty-string"),
        ],
    )
    def test_agent_name(self, agent_name, expected):
        """RangeContext agent_name accepts various values."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeContext

        kwargs = {
            "request_id": uuid.uuid4(),
            "range_id": 42,
            "scenario_id": "basic",
            "user_id": 1,
            "status": ResourceStatus.READY,
            "instances": [],
        }
        if agent_name is not None:
            kwargs["agent_name"] = agent_name
        ctx = RangeContext(**kwargs)
        assert ctx.agent_name == expected

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

    @pytest.mark.parametrize(
        "missing_field,kwargs",
        [
            pytest.param("request_id", {"user_id": 42}, id="request_id"),
            pytest.param("user_id", {"request_id": "placeholder"}, id="user_id"),
            pytest.param("status", {"request_id": "placeholder", "user_id": 42}, id="status"),
        ],
    )
    def test_required_field_missing(self, missing_field, kwargs):
        """RangeRef requires request_id, user_id, and status."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        # Replace placeholder request_id with real UUID
        if kwargs.get("request_id") == "placeholder":
            kwargs["request_id"] = uuid.uuid4()
        if missing_field != "status" and "status" not in kwargs:
            kwargs["status"] = ResourceStatus.READY

        with pytest.raises(ValidationError):
            RangeRef(**kwargs)

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

    @pytest.mark.parametrize("range_id", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")])
    def test_rejects_invalid_range_id(self, range_id):
        """RangeRef rejects zero/negative range_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="range_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=range_id,
                user_id=42,
                status=ResourceStatus.READY,
            )

    @pytest.mark.parametrize("user_id", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")])
    def test_rejects_invalid_user_id(self, user_id):
        """RangeRef rejects zero/negative user_id."""
        from shared.enums import ResourceStatus
        from shared.schemas.range import RangeRef

        with pytest.raises(ValidationError, match="user_id"):
            RangeRef(
                request_id=uuid.uuid4(),
                range_id=123,
                user_id=user_id,
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
