"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Logging (debug and error levels)
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import logging
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.models import AgentConfig, OperatingSystem

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def agent(user, db):
    """Create an agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Test Agent",
        os=os,
        s3_key="agents/test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=1000,
        sha256_hash="abc123",
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
class TestListRanges:
    """Tests for list_ranges() service function.

    Tests SERVICE behavior with mocked model layer:
    - Queries Range model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_range_filter_with_user(self, user):
        """Service queries RangeInstance by user_id."""
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = []
            services.list_ranges(user)
            mock_filter.assert_called_once_with(user_id=user.id)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when no ranges exist."""
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = []
            result = services.list_ranges(user)
            assert result == []

    def test_returns_one_range_when_model_returns_one(self, user):
        """Service returns one range when model returns one."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id, scenario_id="basic")
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_range]
            result = services.list_ranges(user)
            assert len(result) == 1
            assert result[0].range_id == 42

    def test_returns_all_ranges_when_model_returns_multiple(self, user):
        """Service returns all ranges model returns."""
        from cms.models import RangeInstance

        mock_ranges = [Mock(spec=RangeInstance, range_id=i, user_id=user.id, scenario_id="basic") for i in range(5)]
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = mock_ranges
            result = services.list_ranges(user)
            assert len(result) == 5
            assert [r.range_id for r in result] == [0, 1, 2, 3, 4]

    def test_returns_ranges_of_all_scenarios(self, user):
        """Service returns ranges regardless of scenario (no filtering)."""
        from cms.models import RangeInstance

        mock_basic = Mock(spec=RangeInstance, range_id=1, user_id=user.id, scenario_id="basic")
        mock_ad = Mock(spec=RangeInstance, range_id=2, user_id=user.id, scenario_id="ad_attack_lab")
        mock_custom = Mock(spec=RangeInstance, range_id=3, user_id=user.id, scenario_id="custom")
        with patch("cms.services.RangeInstance.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_basic, mock_ad, mock_custom]
            result = services.list_ranges(user)
            assert len(result) == 3
            scenarios = {r.scenario_id for r in result}
            assert scenarios == {"basic", "ad_attack_lab", "custom"}

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_ranges(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        from cms.models import RangeInstance

        mock_ranges = [Mock(spec=RangeInstance) for _ in range(3)]
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value=mock_ranges),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_ranges(user)
        assert "3" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_on_downstream_exception(self, user, caplog):
        """Service logs error when model raises exception."""
        with (
            patch("cms.services.RangeInstance.objects.filter", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.list_ranges(user)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_model_exception(self, user):
        """Service propagates exceptions from model."""
        with (
            patch("cms.services.RangeInstance.objects.filter", side_effect=ValueError("Model error")),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_ranges(user)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of list."""
        with patch("cms.services.RangeInstance.objects.filter", return_value=None), pytest.raises(TypeError):
            services.list_ranges(user)

    def test_raises_on_model_returns_string(self, user):
        """Service raises TypeError if model returns string instead of list."""
        with patch("cms.services.RangeInstance.objects.filter", return_value="not a list"), pytest.raises(TypeError):
            services.list_ranges(user)

    def test_raises_on_model_returns_list_of_wrong_type(self, user):
        """Service raises TypeError if model returns list of wrong type."""
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value=[{"id": 1}, {"id": 2}]),
            pytest.raises(TypeError),
        ):
            services.list_ranges(user)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch("cms.services.RangeInstance.objects.filter", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_ranges(user)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Return type guarantee
    # -------------------------------------------------------------------------

    def test_returns_list_class_not_queryset(self, user):
        """Service returns list class, not QuerySet."""
        from cms.models import RangeInstance

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=RangeInstance)]))
        with patch("cms.services.RangeInstance.objects.filter", return_value=mock_qs):
            result = services.list_ranges(user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, user):
        """Service returns list, not tuple even if model returns tuple."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance)
        with patch("cms.services.RangeInstance.objects.filter", return_value=(mock_range,)):
            result = services.list_ranges(user)
            assert type(result) is list

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.list_ranges()

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.list_ranges(None)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.list_ranges("not-a-user")

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.list_ranges(unsaved_user)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.list_ranges(None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestGetRange:
    """Tests for get_range() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    - Raises CMSError for business logic failures (not found, ownership)
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_objects_get_with_range_id(self, user):
        """Service queries RangeInstance by range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get:
            services.get_range(user, 42)
            mock_get.assert_called_once_with(range_id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_range_when_found_and_owned(self, user):
        """Service returns range instance when it exists and belongs to user."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range):
            result = services.get_range(user, 42)
            assert result.range_id == 42

    def test_returns_range_with_correct_attributes(self, user):
        """Service returns range instance with all attributes intact."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id, scenario_id="basic", agent_id=5)
        with patch("cms.services.RangeInstance.objects.get", return_value=mock_range):
            result = services.get_range(user, 42)
            assert result.scenario_id == "basic"
            assert result.agent_id == 5

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful retrieval."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_range(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, user, caplog):
        """Service logs error when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_range_owned_by_other_user(self, user, caplog):
        """Service logs error when range belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        other_user_id = 999
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=other_user_id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 42)
        assert "error" in caplog.text.lower() or "denied" in caplog.text.lower() or "owner" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, user, caplog):
        """Service logs error when database raises exception."""
        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.get_range(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for business logic failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 999)

    def test_raises_cms_error_when_range_owned_by_other_user(self, user):
        """Service raises CMSError when range belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        other_user_id = 999
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=other_user_id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, user):
        """CMSError message indicates range not found."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_range(user, 999)

    def test_cms_error_has_descriptive_message_for_ownership(self, user):
        """CMSError message indicates ownership violation."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        other_user_id = 999
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=other_user_id)
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match=r"not found|access denied|permission"),
        ):
            services.get_range(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, user):
        """Service propagates unexpected database errors."""
        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.get_range(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.get_range(range_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_range(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.get_range("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.get_range(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_range(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.get_range(user)

    def test_raises_on_none_range_id(self, user):
        """Service raises error if range_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_range(user, None)

    def test_raises_on_invalid_range_id_type(self, user):
        """Service raises error if range_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.get_range(user, "not-an-id")

    def test_raises_on_negative_range_id(self, user):
        """Service raises error if range_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.get_range(user, -1)

    def test_logs_error_on_invalid_range_id(self, user, caplog):
        """Service logs error when given invalid range_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_range(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of range."""
        with patch("cms.services.RangeInstance.objects.get", return_value=None), pytest.raises(TypeError):
            services.get_range(user, 42)

    def test_raises_on_model_returns_wrong_type(self, user):
        """Service raises TypeError if model returns wrong type."""
        with patch("cms.services.RangeInstance.objects.get", return_value="not a range"), pytest.raises(TypeError):
            services.get_range(user, 42)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_range(user, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestCreateRangeValidation:
    """Tests for create_range() validation behavior."""

    def test_raises_for_unknown_scenario(self, user, windows_agent):
        """create_range raises CMSError for unknown scenario_id."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.create_range(user, "nonexistent_scenario", windows_agent.id)

    def test_raises_when_agent_requirements_not_met(self, user, linux_agent):
        """create_range raises CMSError when agent doesn't meet scenario requirements."""
        from cms.exceptions import CMSError

        # ad_attack_lab requires Windows agent
        with pytest.raises(CMSError, match=r"(?i)windows"):
            services.create_range(user, "ad_attack_lab", linux_agent.id)

    def test_raises_when_agent_not_found(self, user):
        """create_range raises CMSError when agent doesn't exist."""
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            services.create_range(user, "basic", 99999)

    def test_raises_when_agent_belongs_to_other_user(self, user, db):
        """create_range raises CMSError when agent belongs to another user."""
        from cms.exceptions import CMSError

        # Create another user with an agent
        other_user = User.objects.create_user(username="other@example.com")
        os = OperatingSystem.objects.get(slug="windows")
        other_agent = AgentConfig.objects.create(
            user=other_user,
            name="Other User Agent",
            os=os,
            s3_key="agents/other/agent.msi",
            original_filename="agent.msi",
            file_size_bytes=1000,
            sha256_hash="xyz789",
        )

        with pytest.raises(CMSError, match="not found"):
            services.create_range(user, "basic", other_agent.id)


@pytest.mark.django_db
class TestCreateRangeEngineCall:
    """Tests for create_range() engine integration."""

    @patch("cms.services.engine_create_range")
    def test_calls_engine_create_range(self, mock_engine, user, windows_agent):
        """create_range calls engine.create_range with RangeRequest."""
        mock_engine.return_value = 42  # Engine returns range_id

        services.create_range(user, "basic", windows_agent.id)

        # Engine should be called once
        mock_engine.assert_called_once()

    @patch("cms.services.engine_create_range")
    def test_engine_receives_range_request(self, mock_engine, user, windows_agent):
        """Engine receives a RangeRequest with scenario and instances."""
        from shared.schemas import RangeRequest

        mock_engine.return_value = 42

        services.create_range(user, "basic", windows_agent.id)

        # Get the RangeRequest passed to engine
        call_args = mock_engine.call_args
        range_request = call_args[0][0]  # First positional arg

        assert isinstance(range_request, RangeRequest)
        assert range_request.scenario_id == "basic"
        assert range_request.user_id == user.id
        assert isinstance(range_request.instances, list)

    @patch("cms.services.engine_create_range")
    def test_range_request_has_correct_scenario_id(self, mock_engine, user, windows_agent):
        """RangeRequest includes the correct scenario_id."""
        mock_engine.return_value = 42

        services.create_range(user, "basic", windows_agent.id)

        range_request = mock_engine.call_args[0][0]
        assert range_request.scenario_id == "basic"

    @patch("cms.services.engine_create_range")
    def test_range_request_has_hydrated_instances(self, mock_engine, user, windows_agent):
        """RangeRequest instances are hydrated with resolved OS and agent."""
        mock_engine.return_value = 42

        services.create_range(user, "basic", windows_agent.id)

        range_request = mock_engine.call_args[0][0]
        instances = range_request.instances

        # Basic scenario has attacker and victim
        assert len(instances) == 2

        victim = next(i for i in instances if i.role == "victim")
        assert victim.os_type == "windows"  # Resolved from agent
        assert victim.agent is not None
        assert victim.agent.s3_key == "agents/123/agent.msi"


@pytest.mark.django_db
class TestCreateRangeInstance:
    """Tests for create_range() RangeInstance storage."""

    @patch("cms.services.engine_create_range")
    def test_creates_range_instance_record(self, mock_engine, user, windows_agent):
        """create_range stores RangeInstance tracking record."""
        from cms.models import RangeInstance

        mock_engine.return_value = 42

        services.create_range(user, "basic", windows_agent.id)

        # RangeInstance should be created
        ri = RangeInstance.objects.get(range_id=42)
        assert ri.scenario_id == "basic"
        assert ri.user_id == user.id
        assert ri.agent_id == windows_agent.id

    @patch("cms.services.engine_create_range")
    def test_range_instance_has_correct_scenario_id(self, mock_engine, user, windows_agent):
        """RangeInstance stores the scenario_id used."""
        from cms.models import RangeInstance

        mock_engine.return_value = 43

        services.create_range(user, "ad_attack_lab", windows_agent.id)

        ri = RangeInstance.objects.get(range_id=43)
        assert ri.scenario_id == "ad_attack_lab"

    @patch("cms.services.engine_create_range")
    def test_range_instance_stores_integer_ids(self, mock_engine, user, windows_agent):
        """RangeInstance stores user_id and agent_id as integers (not FK)."""
        from cms.models import RangeInstance

        mock_engine.return_value = 44

        services.create_range(user, "basic", windows_agent.id)

        ri = RangeInstance.objects.get(range_id=44)
        assert ri.user_id == user.id
        assert ri.agent_id == windows_agent.id
        assert isinstance(ri.user_id, int)
        assert isinstance(ri.agent_id, int)


@pytest.mark.django_db
class TestCreateRangeReturn:
    """Tests for create_range() return value."""

    @patch("cms.services.engine_create_range")
    def test_returns_range_id(self, mock_engine, user, windows_agent):
        """create_range returns the range_id from engine."""
        mock_engine.return_value = 42

        result = services.create_range(user, "basic", windows_agent.id)

        assert result == 42

    @patch("cms.services.engine_create_range")
    def test_returns_integer(self, mock_engine, user, windows_agent):
        """create_range returns an integer range_id."""
        mock_engine.return_value = 100

        result = services.create_range(user, "basic", windows_agent.id)

        assert isinstance(result, int)


@pytest.mark.django_db
class TestCreateRangeLogging:
    """Tests for create_range() logging behavior."""

    @patch("cms.services.engine_create_range")
    def test_logs_debug_on_success(self, mock_engine, user, windows_agent, caplog):
        """create_range logs debug on success."""
        mock_engine.return_value = 50

        with caplog.at_level(logging.DEBUG, logger="cms.services"):
            services.create_range(user, "basic", windows_agent.id)

        assert str(user.id) in caplog.text

    def test_logs_error_when_scenario_not_found(self, user, windows_agent, caplog):
        """create_range logs error when scenario not found."""
        from cms.exceptions import CMSError

        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.create_range(user, "nonexistent", windows_agent.id)

        assert "nonexistent" in caplog.text or "not found" in caplog.text.lower()


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Delegates to engine.orchestration.destroy correctly
    - Returns None (void function)
    - Logs all errors from downstream
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, user):
        """Service calls get_range to verify ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_destroy_range"),
        ):
            services.destroy_range(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_calls_engine_destroy_with_range_id(self, user):
        """Service delegates to engine.destroy_range with range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range") as mock_destroy,
        ):
            services.destroy_range(user, 42)
            mock_destroy.assert_called_once_with(42)

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, user):
        """Service returns None on successful destruction."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range"),
        ):
            result = services.destroy_range(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.destroy_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful destruction."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.destroy_range(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, user, caplog):
        """Service logs error when get_range raises CMSError."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.destroy_range(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_engine_service_fails(self, user, caplog):
        """Service logs error when engine service raises exception."""
        from cms.models import RangeInstance
        from engine.orchestration import OrchestrationError

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range", side_effect=OrchestrationError("No range to destroy")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(OrchestrationError),
        ):
            services.destroy_range(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError

        with patch.object(services, "get_range", side_effect=CMSError("not found")), pytest.raises(CMSError):
            services.destroy_range(user, 999)

    def test_raises_cms_error_when_not_owner(self, user):
        """Service raises CMSError when user doesn't own range (via get_range)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.destroy_range(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    def test_propagates_orchestration_error(self, user):
        """Service propagates OrchestrationError from engine service."""
        from cms.models import RangeInstance
        from engine.orchestration import OrchestrationError

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range", side_effect=OrchestrationError("No range to destroy")),
            pytest.raises(OrchestrationError, match="No range to destroy"),
        ):
            services.destroy_range(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from engine service."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy_range", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.destroy_range(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(range_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.destroy_range("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.destroy_range(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(user)

    def test_raises_on_none_range_id(self, user):
        """Service raises error if range_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(user, None)

    def test_raises_on_invalid_range_id_type(self, user):
        """Service raises error if range_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(user, "not-an-id")

    def test_raises_on_negative_range_id(self, user):
        """Service raises error if range_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(user, -1)

    def test_logs_error_on_invalid_range_id(self, user, caplog):
        """Service logs error when given invalid range_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.destroy_range(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Delegates to engine.orchestration.cancel correctly
    - Returns None (void function)
    - Logs all errors from downstream
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, user):
        """Service calls get_range to verify ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_cancel_range"),
        ):
            services.cancel_range(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_calls_engine_cancel_with_range_id(self, user):
        """Service delegates to engine.cancel_range with range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range") as mock_cancel,
        ):
            services.cancel_range(user, 42)
            mock_cancel.assert_called_once_with(42)

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, user):
        """Service returns None on successful cancellation."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range"),
        ):
            result = services.cancel_range(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful cancellation."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_range(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, user, caplog):
        """Service logs error when get_range raises CMSError."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.cancel_range(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_engine_service_fails(self, user, caplog):
        """Service logs error when engine service raises exception."""
        from cms.models import RangeInstance
        from engine.orchestration import OrchestrationError

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range", side_effect=OrchestrationError("Cannot cancel range")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(OrchestrationError),
        ):
            services.cancel_range(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError

        with patch.object(services, "get_range", side_effect=CMSError("not found")), pytest.raises(CMSError):
            services.cancel_range(user, 999)

    def test_raises_cms_error_when_not_owner(self, user):
        """Service raises CMSError when user doesn't own range (via get_range)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.cancel_range(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    def test_propagates_orchestration_error(self, user):
        """Service propagates OrchestrationError from engine service."""
        from cms.models import RangeInstance
        from engine.orchestration import OrchestrationError

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range", side_effect=OrchestrationError("Cannot cancel range")),
            pytest.raises(OrchestrationError, match="Cannot cancel range"),
        ):
            services.cancel_range(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from engine service."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=user.id)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.cancel_range(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(range_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.cancel_range("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.cancel_range(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(user)

    def test_raises_on_none_range_id(self, user):
        """Service raises error if range_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(user, None)

    def test_raises_on_invalid_range_id_type(self, user):
        """Service raises error if range_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(user, "not-an-id")

    def test_raises_on_negative_range_id(self, user):
        """Service raises error if range_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(user, -1)

    def test_logs_error_on_invalid_range_id(self, user, caplog):
        """Service logs error when given invalid range_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.cancel_range(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestPauseRange:
    """Tests for pause_range() service function.

    Per plan: Deferred - should remain as NotImplementedError.
    """

    def test_raises_not_implemented_error(self, user):
        """Service raises NotImplementedError (deferred feature)."""
        with pytest.raises(NotImplementedError):
            services.pause_range(user, 42)


@pytest.mark.django_db
class TestResumeRange:
    """Tests for resume_range() service function.

    Per plan: Deferred - should remain as NotImplementedError.
    """

    def test_raises_not_implemented_error(self, user):
        """Service raises NotImplementedError (deferred feature)."""
        with pytest.raises(NotImplementedError):
            services.resume_range(user, 42)
