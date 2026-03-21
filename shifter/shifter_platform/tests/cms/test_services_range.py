"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest

from cms import services
from tests.conftest import INVALID_RANGE_IDS, INVALID_USERS


def make_mock_request(request_id: UUID | None = None) -> Mock:
    """Create a mock Request object with request_id attribute."""
    mock_request = Mock()
    mock_request.request_id = request_id or uuid4()
    return mock_request


def _make_mock_agent(*, pk, name, os_slug, s3_key, original_filename, sha256_hash):
    """Create a mock agent with attributes the service accesses."""
    mock_os = Mock()
    mock_os.slug = os_slug
    agent = Mock()
    agent.pk = pk
    agent.id = pk
    agent.name = name
    agent.os = mock_os
    agent.s3_key = s3_key
    agent.original_filename = original_filename
    agent.sha256_hash = sha256_hash
    return agent


@pytest.fixture
def mock_user():
    user = Mock()
    user.pk = 42
    user.id = 42
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_windows_agent():
    """Mock Windows agent for testing."""
    return _make_mock_agent(
        pk=10,
        name="Windows Agent",
        os_slug="windows",
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        sha256_hash="abc123def456",
    )


@pytest.fixture
def mock_linux_agent():
    """Mock Linux agent for testing."""
    return _make_mock_agent(
        pk=20,
        name="Linux Agent",
        os_slug="linux-debian",
        s3_key="agents/456/agent.deb",
        original_filename="cortex_agent.deb",
        sha256_hash="def789ghi012",
    )


class TestListRanges:
    """Tests for list_ranges() service function.

    Tests SERVICE behavior with mocked model layer:
    - Queries Range model correctly
    - Returns what model returns
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_range_filter_with_user(self, mock_user):
        """Service queries RangeInstance by user_id."""
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = []
            services.list_ranges(mock_user)
            mock_filter.assert_called_once_with(user_id=mock_user.id)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_empty_list_when_model_returns_empty(self, mock_user):
        """Service returns empty list when no ranges exist."""
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = []
            result = services.list_ranges(mock_user)
            assert result == []

    def test_returns_one_range_when_model_returns_one(self, mock_user):
        """Service returns one range when model returns one."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_range]
            result = services.list_ranges(mock_user)
            assert len(result) == 1
            assert result[0].range_id == 42

    def test_returns_all_ranges_when_model_returns_multiple(self, mock_user):
        """Service returns all ranges model returns."""
        from cms.models import RangeInstance

        mock_ranges = [
            Mock(spec=RangeInstance, range_id=i, user_id=mock_user.id, scenario_id="basic") for i in range(5)
        ]
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = mock_ranges
            result = services.list_ranges(mock_user)
            assert len(result) == 5
            assert [r.range_id for r in result] == [0, 1, 2, 3, 4]

    def test_returns_ranges_of_all_scenarios(self, mock_user):
        """Service returns ranges regardless of scenario (no filtering)."""
        from cms.models import RangeInstance

        mock_basic = Mock(spec=RangeInstance, range_id=1, user_id=mock_user.id, scenario_id="basic")
        mock_ad = Mock(spec=RangeInstance, range_id=2, user_id=mock_user.id, scenario_id="ad_attack_lab")
        mock_custom = Mock(spec=RangeInstance, range_id=3, user_id=mock_user.id, scenario_id="custom")
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_basic, mock_ad, mock_custom]
            result = services.list_ranges(mock_user)
            assert len(result) == 3
            scenarios = {r.scenario_id for r in result}
            assert scenarios == {"basic", "ad_attack_lab", "custom"}

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_model_exception(self, mock_user):
        """Service propagates exceptions from model."""
        with (
            patch(
                "cms.services.RangeInstance.objects.filter",
                side_effect=ValueError("Model error"),
            ),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_ranges(mock_user)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, mock_user):
        """Service raises TypeError if model returns None instead of list."""
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value=None),
            pytest.raises(TypeError),
        ):
            services.list_ranges(mock_user)

    def test_raises_on_model_returns_string(self, mock_user):
        """Service raises TypeError if model returns string instead of list."""
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value="not a list"),
            pytest.raises(TypeError),
        ):
            services.list_ranges(mock_user)

    def test_raises_on_model_returns_list_of_wrong_type(self, mock_user):
        """Service raises TypeError if model returns list of wrong type."""
        with (
            patch(
                "cms.services.RangeInstance.objects.filter",
                return_value=[{"id": 1}, {"id": 2}],
            ),
            pytest.raises(TypeError),
        ):
            services.list_ranges(mock_user)

    # -------------------------------------------------------------------------
    # Return type guarantee
    # -------------------------------------------------------------------------

    def test_returns_list_class_not_queryset(self, mock_user):
        """Service returns list class, not QuerySet."""
        from cms.models import RangeInstance

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=RangeInstance)]))
        with patch("cms.services.RangeInstance.objects.filter", return_value=mock_qs):
            result = services.list_ranges(mock_user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, mock_user):
        """Service returns list, not tuple even if model returns tuple."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance)
        with patch("cms.services.RangeInstance.objects.filter", return_value=(mock_range,)):
            result = services.list_ranges(mock_user)
            assert type(result) is list

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.list_ranges()

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.list_ranges(invalid_user)


class TestGetRange:
    """Tests for get_range() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Validates input
    - Propagates errors
    - Raises CMSError for business logic failures (not found, ownership)
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_objects_get_with_range_id(self, mock_user):
        """Service queries RangeInstance by range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get:
            services.get_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_range_when_found_and_owned(self, mock_user):
        """Service returns range instance when it exists and belongs to user."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range):
            result = services.get_range(mock_user, 42)
            assert result.range_id == 42

    def test_returns_range_with_correct_attributes(self, mock_user):
        """Service returns range instance with all attributes intact."""
        from cms.models import RangeInstance

        mock_range = Mock(
            spec=RangeInstance,
            range_id=42,
            user_id=mock_user.id,
            scenario_id="basic",
            agent_id=5,
        )
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range):
            result = services.get_range(mock_user, 42)
            assert result.scenario_id == "basic"
            assert result.agent_id == 5

    # -------------------------------------------------------------------------
    # Error handling - CMSError for business logic failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch(
                "cms.services.RangeInstance.objects.get",
                side_effect=RangeInstance.DoesNotExist,
            ),
            pytest.raises(CMSError),
        ):
            services.get_range(mock_user, 999)

    def test_raises_cms_error_when_range_owned_by_other_user(self, mock_user):
        """Service raises CMSError when range belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        other_user_id = 999
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=other_user_id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError),
        ):
            services.get_range(mock_user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, mock_user):
        """CMSError message indicates range not found."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch(
                "cms.services.RangeInstance.objects.get",
                side_effect=RangeInstance.DoesNotExist,
            ),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_range(mock_user, 999)

    def test_cms_error_has_descriptive_message_for_ownership(self, mock_user):
        """CMSError message indicates ownership violation."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        other_user_id = 999
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=other_user_id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match=r"not found|access denied|permission"),
        ):
            services.get_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, mock_user):
        """Service propagates unexpected database errors."""
        with (
            patch(
                "cms.services.RangeInstance.objects.get",
                side_effect=Exception("DB connection failed"),
            ),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.get_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.get_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.get_range(invalid_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, mock_user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.get_range(mock_user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, mock_user, invalid_range_id):
        """Service raises error for invalid range_id values."""
        with pytest.raises((TypeError, ValueError)):
            services.get_range(mock_user, invalid_range_id)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, mock_user):
        """Service raises TypeError if model returns None instead of range."""
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=None),
            pytest.raises(TypeError),
        ):
            services.get_range(mock_user, 42)

    def test_raises_on_model_returns_wrong_type(self, mock_user):
        """Service raises TypeError if model returns wrong type."""
        with (
            patch("cms.services.RangeInstance.objects.get", return_value="not a range"),
            pytest.raises(TypeError),
        ):
            services.get_range(mock_user, 42)


class TestCreateRangeValidation:
    """Tests for create_range() validation behavior."""

    @patch("cms.services.get_active_range", return_value=None)
    def test_raises_for_unknown_scenario(self, _mock_active, mock_user, mock_windows_agent):
        """create_range raises CMSError for unknown scenario_id."""
        from cms.exceptions import CMSError

        with (
            patch(
                "cms.scenarios.registry.load_scenario_template",
                side_effect=ValueError("not found"),
            ),
            pytest.raises(CMSError, match="not found"),
        ):
            services.create_range(mock_user, "nonexistent_scenario", {"windows": mock_windows_agent.id})

    @patch("cms.services.get_active_range", return_value=None)
    def test_raises_when_agent_not_found(self, _mock_active, mock_user):
        """create_range raises CMSError when agent doesn't exist."""
        from cms.exceptions import CMSError

        mock_template = Mock()
        mock_template.get_agent_requirements.return_value = {
            "requires_windows": False,
            "requires_linux": False,
            "has_from_agent": True,
        }

        with (
            patch("cms.scenarios.registry.load_scenario_template", return_value=mock_template),
            patch("cms.services.get_agent", side_effect=CMSError("Agent 99999 not found")),
            pytest.raises(CMSError, match="not found"),
        ):
            services.create_range(mock_user, "basic", {"windows": 99999})

    @patch("cms.services.get_active_range", return_value=None)
    def test_raises_when_agent_belongs_to_other_user(self, _mock_active, mock_user):
        """create_range raises CMSError when agent belongs to another user."""
        from cms.exceptions import CMSError

        mock_template = Mock()
        mock_template.get_agent_requirements.return_value = {
            "requires_windows": False,
            "requires_linux": False,
            "has_from_agent": True,
        }

        with (
            patch("cms.scenarios.registry.load_scenario_template", return_value=mock_template),
            patch("cms.services.get_agent", side_effect=CMSError("Agent not found")),
            pytest.raises(CMSError, match="not found"),
        ):
            services.create_range(mock_user, "basic", {"windows": 999})

    def test_raises_when_user_already_has_active_range(self, mock_user):
        """create_range raises CMSError when user has an existing active range."""
        from cms.exceptions import CMSError

        mock_existing = Mock()
        mock_existing.range_id = 100

        with (
            patch("cms.services.get_active_range", return_value=mock_existing),
            pytest.raises(CMSError, match="already have an active range"),
        ):
            services.create_range(mock_user, "basic", {"windows": 10})


@pytest.fixture
def create_range_ctx(mock_user, mock_windows_agent):
    """Fixture providing common mocks for create_range tests.

    Mocks all ORM access so tests run without a database.
    Yields a dict of mock objects; ExitStack is auto-closed on teardown.
    """
    from contextlib import ExitStack

    from shared.schemas import (
        AgentDetails,
        InstanceSpec,
        RangeSpec,
        SubnetSpec,
    )

    mock_template = Mock()
    mock_template.get_agent_requirements.return_value = {
        "requires_windows": False,
        "requires_linux": False,
        "has_from_agent": True,
    }
    mock_template.ngfw = False

    attacker_spec = InstanceSpec(
        name="Attacker",
        uuid=str(uuid4()),
        role="attacker",
        os_type="kali",
    )
    victim_spec = InstanceSpec(
        name="Victim",
        uuid=str(uuid4()),
        role="victim",
        os_type="windows",
        agent=AgentDetails(
            s3_key=mock_windows_agent.s3_key,
            filename=mock_windows_agent.original_filename,
            sha256=mock_windows_agent.sha256_hash,
        ),
    )
    canned_range_spec = RangeSpec(
        uuid=str(uuid4()),
        scenario_id="basic",
        user_id=mock_user.id,
        subnets=[
            SubnetSpec(
                name="default",
                uuid=str(uuid4()),
                instances=[attacker_spec, victim_spec],
                connected_to=[],
            )
        ],
        ngfw=False,
    )

    mock_request = Mock()
    mock_request.request_id = uuid4()
    mock_ri = Mock()

    with ExitStack() as stack:
        mocks = {}
        mocks["active_range"] = stack.enter_context(patch("cms.services.get_active_range", return_value=None))
        mocks["load_scenario"] = stack.enter_context(
            patch("cms.scenarios.registry.load_scenario_template", return_value=mock_template)
        )
        mocks["get_agent"] = stack.enter_context(patch("cms.services.get_agent", return_value=mock_windows_agent))
        mocks["hydrate"] = stack.enter_context(
            patch("cms.scenarios.hydrator.hydrate_scenario", return_value=canned_range_spec)
        )
        mocks["request_create"] = stack.enter_context(
            patch("cms.models.Request.objects.create", return_value=mock_request)
        )
        mocks["engine"] = stack.enter_context(patch("cms.services.engine_create_range"))
        mocks["ri_create"] = stack.enter_context(
            patch("cms.services.RangeInstance.objects.create", return_value=mock_ri)
        )
        mocks["audit"] = stack.enter_context(patch("cms.services.audit_log"))
        mocks["range_spec"] = canned_range_spec
        yield mocks


class TestCreateRangeEngineCall:
    """Tests for create_range() engine integration."""

    def test_calls_engine_create_range(self, mock_user, mock_windows_agent, create_range_ctx):
        """create_range calls engine.create_range with RangeSpec."""
        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        create_range_ctx["engine"].assert_called_once()

    def test_engine_receives_request_spec(self, mock_user, mock_windows_agent, create_range_ctx):
        """Engine receives a RequestSpec containing RangeSpec."""
        from shared.schemas import RangeSpec, RequestSpec

        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})

        call_args = create_range_ctx["engine"].call_args
        request_spec = call_args[0][0]

        assert isinstance(request_spec, RequestSpec)
        assert request_spec.user_id == mock_user.id
        assert len(request_spec.items) == 1
        range_spec = request_spec.items[0]
        assert isinstance(range_spec, RangeSpec)
        assert range_spec.scenario_id == "basic"
        assert isinstance(range_spec.all_instances, list)

    def test_range_request_has_correct_scenario_id(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeSpec inside RequestSpec includes the correct scenario_id."""
        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})

        request_spec = create_range_ctx["engine"].call_args[0][0]
        range_spec = request_spec.items[0]
        assert range_spec.scenario_id == "basic"

    def test_range_request_has_hydrated_instances(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeSpec instances are hydrated with resolved OS and agent."""
        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})

        request_spec = create_range_ctx["engine"].call_args[0][0]
        range_spec = request_spec.items[0]
        instances = range_spec.all_instances

        assert len(instances) == 2

        victim = next(i for i in instances if i.role == "victim")
        assert victim.os_type == "windows"
        assert victim.agent is not None
        assert victim.agent.s3_key == "agents/123/agent.msi"


class TestCreateRangeInstance:
    """Tests for create_range() RangeInstance storage."""

    def test_creates_range_instance_record(self, mock_user, mock_windows_agent, create_range_ctx):
        """create_range calls RangeInstance.objects.create with correct args."""
        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})

        create_range_ctx["ri_create"].assert_called_once()
        call_kwargs = create_range_ctx["ri_create"].call_args[1]
        assert call_kwargs["scenario_id"] == "basic"
        assert call_kwargs["user_id"] == mock_user.id
        assert call_kwargs["agent"] == mock_windows_agent

    def test_range_instance_has_correct_scenario_id(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeInstance.objects.create receives the scenario_id used."""
        canned = create_range_ctx["range_spec"]
        canned_ad = canned.model_copy(update={"scenario_id": "ad_attack_lab"})
        create_range_ctx["hydrate"].return_value = canned_ad

        services.create_range(mock_user, "ad_attack_lab", {"windows": mock_windows_agent.id})

        call_kwargs = create_range_ctx["ri_create"].call_args[1]
        assert call_kwargs["scenario_id"] == "ad_attack_lab"

    def test_range_instance_stores_integer_ids(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeInstance.objects.create receives user_id and agent as expected types."""
        services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})

        call_kwargs = create_range_ctx["ri_create"].call_args[1]
        assert call_kwargs["user_id"] == mock_user.id
        assert isinstance(call_kwargs["user_id"], int)


class TestCreateRangeReturn:
    """Tests for create_range() return value."""

    def test_returns_range_context(self, mock_user, mock_windows_agent, create_range_ctx):
        """create_range returns a RangeContext."""
        from shared.schemas.range import RangeContext

        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert isinstance(result, RangeContext)

    def test_range_context_has_request_id(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext contains request_id (range_id is None for new ranges)."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert result.request_id is not None
        assert result.range_id is None

    def test_range_context_has_scenario_id(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext contains the scenario_id."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert result.scenario_id == "basic"

    def test_range_context_has_user_id(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext contains the user_id."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert result.user_id == mock_user.id

    def test_range_context_has_agent_name(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext contains the agent_name."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert result.agent_name == "Windows Agent"

    def test_range_context_has_provisioning_status(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext has PROVISIONING status (engine invariant on creation)."""
        from shared.enums import ResourceStatus

        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert result.status == ResourceStatus.PROVISIONING

    def test_range_context_has_instances(self, mock_user, mock_windows_agent, create_range_ctx):
        """RangeContext contains instances list."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        assert len(result.instances) == 2  # basic scenario has attacker + victim

    def test_instances_have_uuids(self, mock_user, mock_windows_agent, create_range_ctx):
        """Each instance has a UUID."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        for instance in result.instances:
            assert instance.uuid is not None

    def test_instances_have_roles(self, mock_user, mock_windows_agent, create_range_ctx):
        """Instances have correct roles from scenario."""
        result = services.create_range(mock_user, "basic", {"windows": mock_windows_agent.id})
        roles = [i.role for i in result.instances]
        assert "attacker" in roles
        assert "victim" in roles


class TestDestroyRange:
    """Tests for destroy_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Delegates to engine.orchestration.destroy correctly
    - Returns None (void function)
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_destroy_range_by_request"),
        ):
            services.destroy_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_updates_status_to_destroying(self, mock_user):
        """Service sets status to DESTROYING and soft deletes before calling engine."""
        from django.utils import timezone

        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()

        mock_now = timezone.now()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request"),
            patch("django.utils.timezone.now", return_value=mock_now),
        ):
            services.destroy_range(mock_user, 42)

            # Verify status was set to DESTROYING
            assert mock_range.status == ResourceStatus.DESTROYING.value
            # Verify deleted_at was set (soft delete)
            assert mock_range.deleted_at == mock_now
            # Verify save was called with both fields
            mock_range.save.assert_called_once_with(update_fields=["status", "deleted_at"])

    def test_calls_engine_destroy_with_request_id(self, mock_user):
        """Service passes request_id (not RangeContext) to engine."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = mock_request
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request") as mock_destroy,
        ):
            services.destroy_range(mock_user, 42)

            # Verify engine was called with request_id
            mock_destroy.assert_called_once()
            call_arg = mock_destroy.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, mock_user):
        """Service returns None on successful destruction."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request"),
        ):
            result = services.destroy_range(mock_user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch(
                "cms.services.RangeInstance.objects.get",
                side_effect=RangeInstance.DoesNotExist,
            ),
            pytest.raises(CMSError, match="Range 999 not found"),
        ):
            services.destroy_range(mock_user, 999)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        # Create mock instance owned by different user
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=999, scenario_id="basic")
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="Range 42 not found"),
        ):
            services.destroy_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "exc_class,exc_msg",
        [
            pytest.param("EngineError", "No range to destroy", id="engine-error"),
            pytest.param("Exception", "DB connection failed", id="unexpected"),
        ],
    )
    def test_propagates_error(self, mock_user, exc_class, exc_msg):
        """Service propagates errors from engine service."""
        from cms.models import RangeInstance
        from engine import EngineError

        exc_type = EngineError if exc_class == "EngineError" else Exception
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request", side_effect=exc_type(exc_msg)),
            pytest.raises(exc_type, match=exc_msg),
        ):
            services.destroy_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.destroy_range(invalid_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, mock_user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(mock_user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, mock_user, invalid_range_id):
        """Service raises error for invalid range_id values."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(mock_user, invalid_range_id)


class TestCancelRange:
    """Tests for cancel_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Updates status to DESTROYED before calling engine
    - Passes RangeContext to engine (not range_id)
    - Returns None (void function)
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and updates status
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service calls get_range to verify ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            services.cancel_range(mock_user, 42)
            mock_get.assert_called_once_with(mock_user, 42)

    def test_updates_status_to_destroyed(self, mock_user):
        """Service sets status to DESTROYED before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            services.cancel_range(mock_user, 42)

            # Verify status was set
            assert mock_range.status == ResourceStatus.DESTROYED.value
            # Verify save was called with update_fields
            mock_range.save.assert_called_once_with(update_fields=["status"])

    def test_calls_engine_cancel_with_request_id(self, mock_user):
        """Service passes request_id (not RangeContext) to engine."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = mock_request
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request") as mock_cancel,
        ):
            services.cancel_range(mock_user, 42)

            # Verify engine was called with request_id
            mock_cancel.assert_called_once()
            call_arg = mock_cancel.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, mock_user):
        """Service returns None on successful cancellation."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            result = services.cancel_range(mock_user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("not found")),
            pytest.raises(CMSError),
        ):
            services.cancel_range(mock_user, 999)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own range (via get_range)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.cancel_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "exc_class,exc_msg",
        [
            pytest.param("EngineError", "Cannot cancel range", id="engine-error"),
            pytest.param("Exception", "DB connection failed", id="unexpected"),
        ],
    )
    def test_propagates_error(self, mock_user, exc_class, exc_msg):
        """Service propagates errors from engine service."""
        from cms.models import RangeInstance
        from engine import EngineError

        exc_type = EngineError if exc_class == "EngineError" else Exception
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request", side_effect=exc_type(exc_msg)),
            pytest.raises(exc_type, match=exc_msg),
        ):
            services.cancel_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.cancel_range(invalid_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, mock_user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(mock_user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, mock_user, invalid_range_id):
        """Service raises error for invalid range_id values."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(mock_user, invalid_range_id)


class TestPauseRange:
    """Tests for pause_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via RangeInstance lookup
    - Delegates to engine.pause_range correctly
    - Raises CMSError when engine returns False
    """

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_pause_range", return_value=True),
        ):
            services.pause_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_calls_engine_pause_with_request_id(self, mock_user):
        """Service passes request_id to engine.pause_range."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=True) as mock_pause,
        ):
            services.pause_range(mock_user, 42)

            mock_pause.assert_called_once()
            call_arg = mock_pause.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    def test_raises_cms_error_when_engine_returns_false(self, mock_user):
        """Service raises CMSError when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            services.pause_range(mock_user, 42)

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError, match="not found"),
        ):
            services.pause_range(mock_user, 42)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own the range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id + 1)  # Different user
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="not found"),
        ):
            services.pause_range(mock_user, 42)

    def test_sets_status_to_pausing_before_engine_call(self, mock_user):
        """Service sets CMS status to PAUSING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        statuses_at_engine_call = []

        def capture_status(request_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", side_effect=capture_status),
        ):
            services.pause_range(mock_user, 42)

        assert statuses_at_engine_call == [ResourceStatus.PAUSING.value]

    def test_reverts_status_to_ready_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to READY when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            services.pause_range(mock_user, 42)

        assert mock_range.status == ResourceStatus.READY.value


class TestResumeRange:
    """Tests for resume_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via RangeInstance lookup
    - Delegates to engine.resume_range correctly
    - Raises CMSError when engine returns False
    """

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_resume_range", return_value=True),
        ):
            services.resume_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_calls_engine_resume_with_request_id(self, mock_user):
        """Service passes request_id to engine.resume_range."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=True) as mock_resume,
        ):
            services.resume_range(mock_user, 42)

            mock_resume.assert_called_once()
            call_arg = mock_resume.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    def test_raises_cms_error_when_engine_returns_false(self, mock_user):
        """Service raises CMSError when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            services.resume_range(mock_user, 42)

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError, match="not found"),
        ):
            services.resume_range(mock_user, 42)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own the range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id + 1)  # Different user
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="not found"),
        ):
            services.resume_range(mock_user, 42)

    def test_sets_status_to_resuming_before_engine_call(self, mock_user):
        """Service sets CMS status to RESUMING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        statuses_at_engine_call = []

        def capture_status(request_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", side_effect=capture_status),
        ):
            services.resume_range(mock_user, 42)

        assert statuses_at_engine_call == [ResourceStatus.RESUMING.value]

    def test_reverts_status_to_paused_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to PAUSED when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            services.resume_range(mock_user, 42)

        assert mock_range.status == ResourceStatus.PAUSED.value


class TestPauseRangeByRequestId:
    """Tests for pause_range_by_request_id() service function."""

    def test_calls_engine_with_request_id(self, mock_user):
        """Service passes request_id to engine.pause_range."""
        from cms.models import RangeInstance

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", return_value=True) as mock_pause,
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

            mock_pause.assert_called_once_with(request_id)

    def test_sets_status_to_pausing_before_engine_call(self, mock_user):
        """Service sets CMS status to PAUSING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        statuses_at_engine_call = []

        def capture_status(req_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", side_effect=capture_status),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

        assert statuses_at_engine_call == [ResourceStatus.PAUSING.value]

    def test_reverts_status_to_ready_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to READY when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

        assert mock_range.status == ResourceStatus.READY.value

    def test_raises_cms_error_when_not_found(self, mock_user):
        """Service raises CMSError when range not found."""
        from cms.exceptions import CMSError

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            pytest.raises(CMSError, match="not found"),
        ):
            mock_filter.return_value.first.return_value = None
            services.pause_range_by_request_id(mock_user, str(uuid4()))


class TestResumeRangeByRequestId:
    """Tests for resume_range_by_request_id() service function."""

    def test_calls_engine_with_request_id(self, mock_user):
        """Service passes request_id to engine.resume_range."""
        from cms.models import RangeInstance

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", return_value=True) as mock_resume,
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

            mock_resume.assert_called_once_with(request_id)

    def test_sets_status_to_resuming_before_engine_call(self, mock_user):
        """Service sets CMS status to RESUMING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        statuses_at_engine_call = []

        def capture_status(req_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", side_effect=capture_status),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

        assert statuses_at_engine_call == [ResourceStatus.RESUMING.value]

    def test_reverts_status_to_paused_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to PAUSED when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

        assert mock_range.status == ResourceStatus.PAUSED.value

    def test_raises_cms_error_when_not_found(self, mock_user):
        """Service raises CMSError when range not found."""
        from cms.exceptions import CMSError

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            pytest.raises(CMSError, match="not found"),
        ):
            mock_filter.return_value.first.return_value = None
            services.resume_range_by_request_id(mock_user, str(uuid4()))
