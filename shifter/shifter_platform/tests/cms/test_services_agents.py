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


@pytest.mark.django_db
class TestListAgents:
    """Tests for list_agents() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # --- Service calls model correctly ---

    def test_calls_active_for_user_with_user(self, user):
        """Service calls AgentConfig.active_for_user with the user."""
        mock_qs = Mock()
        mock_qs.select_related.return_value = []
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs) as mock_active:
            services.list_agents(user)
            mock_active.assert_called_once_with(user)

    # --- Service returns projection dicts ---

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when model returns empty queryset."""
        mock_qs = Mock()
        mock_qs.select_related.return_value = []
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            assert result == []

    def test_returns_one_agent_dict_when_model_returns_one(self, user):
        """Service returns one agent dict when model returns one."""
        mock_os = Mock()
        mock_os.name = "Windows"
        mock_os.slug = "windows"
        mock_agent = Mock(spec=AgentConfig, id=42, os=mock_os, file_size_mb=50)
        mock_agent.name = "Mock Agent"
        mock_qs = Mock()
        mock_qs.select_related.return_value = [mock_agent]
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            assert len(result) == 1
            assert result[0]["id"] == 42
            assert result[0]["name"] == "Mock Agent"
            assert result[0]["os_slug"] == "windows"

    def test_returns_five_agent_dicts_when_model_returns_five(self, user):
        """Service returns all agents as dicts."""
        mock_os = Mock(name="Windows", slug="windows")
        mock_agents = [Mock(spec=AgentConfig, id=i, name=f"Agent {i}", os=mock_os, file_size_mb=10) for i in range(5)]
        mock_qs = Mock()
        mock_qs.select_related.return_value = mock_agents
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            assert len(result) == 5
            assert [a["id"] for a in result] == [0, 1, 2, 3, 4]

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        mock_qs = Mock()
        mock_qs.select_related.return_value = []
        with (
            patch.object(AgentConfig, "active_for_user", return_value=mock_qs),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_agents(user)
        assert str(user.id) in caplog.text or user.email in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        mock_os = Mock(name="Windows", slug="windows")
        mock_agents = [Mock(spec=AgentConfig, id=i, name=f"Agent {i}", os=mock_os, file_size_mb=10) for i in range(3)]
        mock_qs = Mock()
        mock_qs.select_related.return_value = mock_agents
        with (
            patch.object(AgentConfig, "active_for_user", return_value=mock_qs),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_agents(user)
        assert "3" in caplog.text

    def test_logs_error_on_downstream_exception(self, user, caplog):
        """Service logs error when model raises exception."""
        with (
            patch.object(AgentConfig, "active_for_user", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.list_agents(user)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_model_exception(self, user):
        """Service propagates exceptions from model."""
        with (
            patch.object(AgentConfig, "active_for_user", side_effect=ValueError("Model error")),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_agents(user)

    # --- Response validation (model returns garbage) ---

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of list."""
        with patch.object(AgentConfig, "active_for_user", return_value=None), pytest.raises(TypeError):
            services.list_agents(user)

    def test_raises_on_model_returns_string(self, user):
        """Service raises TypeError if model returns string instead of list."""
        with patch.object(AgentConfig, "active_for_user", return_value="not a list"), pytest.raises(TypeError):
            services.list_agents(user)

    def test_raises_on_model_returns_dict(self, user):
        """Service raises TypeError if model returns dict instead of list."""
        mock_qs = Mock()
        mock_qs.select_related.return_value = None
        with (
            patch.object(AgentConfig, "active_for_user", return_value={"agents": []}),
            pytest.raises(TypeError),
        ):
            services.list_agents(user)

    def test_raises_on_model_returns_list_of_strings(self, user):
        """Service raises TypeError if model returns list of wrong type."""
        with (
            patch.object(AgentConfig, "active_for_user", return_value=["a", "b", "c"]),
            pytest.raises(TypeError),
        ):
            services.list_agents(user)

    def test_raises_on_model_returns_list_of_dicts(self, user):
        """Service raises TypeError if model returns list of dicts instead of AgentConfig."""
        with (
            patch.object(AgentConfig, "active_for_user", return_value=[{"id": 1}, {"id": 2}]),
            pytest.raises(TypeError),
        ):
            services.list_agents(user)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch.object(AgentConfig, "active_for_user", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_agents(user)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()

    def test_logs_error_on_model_returns_none(self, user, caplog):
        """Service logs error when model returns None."""
        mock_qs = Mock()
        mock_qs.select_related.return_value = None
        with (
            patch.object(AgentConfig, "active_for_user", return_value=mock_qs),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_agents(user)
        assert "none" in caplog.text.lower() or "error" in caplog.text.lower()

    # --- Return type guarantee ---

    def test_returns_list_of_dicts(self, user):
        """Service returns list of dicts, not model instances."""
        mock_os = Mock()
        mock_os.name = "Windows"
        mock_os.slug = "windows"
        mock_agent = Mock(
            spec=AgentConfig, id=1, os=mock_os, file_size_mb=10
        )
        mock_agent.name = "Agent"
        mock_qs = Mock()
        mock_qs.select_related.return_value = [mock_agent]
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            assert type(result) is list
            assert type(result[0]) is dict

    def test_dict_has_required_keys(self, user):
        """Each dict has id, name, os_name, os_slug, file_size_mb."""
        mock_os = Mock()
        mock_os.name = "Windows"
        mock_os.slug = "windows"
        mock_agent = Mock(
            spec=AgentConfig, id=1, os=mock_os, file_size_mb=10
        )
        mock_agent.name = "Agent"
        mock_qs = Mock()
        mock_qs.select_related.return_value = [mock_agent]
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            agent = result[0]
            assert "id" in agent
            assert "name" in agent
            assert "os_name" in agent
            assert "os_slug" in agent
            assert "file_size_mb" in agent

    def test_dict_values_have_correct_types(self, user):
        """Dict values have correct types: id=int, strings, file_size_mb=number."""
        mock_os = Mock()
        mock_os.name = "Windows"
        mock_os.slug = "windows"
        mock_agent = Mock(
            spec=AgentConfig, id=42, os=mock_os, file_size_mb=50
        )
        mock_agent.name = "Test Agent"
        mock_qs = Mock()
        mock_qs.select_related.return_value = [mock_agent]
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            agent = result[0]
            assert isinstance(agent["id"], int)
            assert isinstance(agent["name"], str)
            assert isinstance(agent["os_name"], str)
            assert isinstance(agent["os_slug"], str)
            assert isinstance(agent["file_size_mb"], (int, float))

    # --- Input validation ---

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.list_agents()

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.list_agents(None)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.list_agents("not-a-user")

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        # User exists but has no ID yet
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.list_agents(unsaved_user)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.list_agents(None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestGetAgent:
    """Tests for get_agent() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    - Raises CMSError for business logic failures (not found, ownership, deleted)
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_objects_get_with_agent_id(self, user):
        """Service queries AgentConfig by id."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with patch.object(AgentConfig.objects, "get", return_value=mock_agent) as mock_get:
            services.get_agent(user, 42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_agent_when_found_and_owned(self, user):
        """Service returns agent when it exists and belongs to user."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with patch.object(AgentConfig.objects, "get", return_value=mock_agent):
            result = services.get_agent(user, 42)
            assert result.id == 42

    def test_returns_agent_with_correct_attributes(self, user):
        """Service returns agent with all attributes intact."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        mock_agent.configure_mock(name="Test Agent")  # name is special param in Mock
        with patch.object(AgentConfig.objects, "get", return_value=mock_agent):
            result = services.get_agent(user, 42)
            assert result.name == "Test Agent"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and agent_id."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_agent(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful retrieval."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_agent(user, 42)
        # Should log something indicating success
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_agent_not_found(self, user, caplog):
        """Service logs error when agent doesn't exist."""
        from cms.exceptions import CMSError

        with (
            patch.object(AgentConfig.objects, "get", side_effect=AgentConfig.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_agent_owned_by_other_user(self, user, caplog):
        """Service logs error when agent belongs to different user."""
        from cms.exceptions import CMSError

        other_user = Mock(id=999)
        mock_agent = Mock(spec=AgentConfig, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 42)
        assert "error" in caplog.text.lower() or "denied" in caplog.text.lower() or "owner" in caplog.text.lower()

    def test_logs_error_when_agent_is_deleted(self, user, caplog):
        """Service logs error when agent is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError

        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 42)
        assert "error" in caplog.text.lower() or "deleted" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, user, caplog):
        """Service logs error when database raises exception."""
        with (
            patch.object(AgentConfig.objects, "get", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.get_agent(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for business logic failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_agent_not_found(self, user):
        """Service raises CMSError when agent doesn't exist."""
        from cms.exceptions import CMSError

        with (
            patch.object(AgentConfig.objects, "get", side_effect=AgentConfig.DoesNotExist),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 999)

    def test_raises_cms_error_when_agent_owned_by_other_user(self, user):
        """Service raises CMSError when agent belongs to different user."""
        from cms.exceptions import CMSError

        other_user = Mock(id=999)
        mock_agent = Mock(spec=AgentConfig, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 42)

    def test_raises_cms_error_when_agent_is_deleted(self, user):
        """Service raises CMSError when agent is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError

        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            pytest.raises(CMSError),
        ):
            services.get_agent(user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, user):
        """CMSError message indicates agent not found."""
        from cms.exceptions import CMSError

        with (
            patch.object(AgentConfig.objects, "get", side_effect=AgentConfig.DoesNotExist),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_agent(user, 999)

    def test_cms_error_has_descriptive_message_for_ownership(self, user):
        """CMSError message indicates ownership violation."""
        from cms.exceptions import CMSError

        other_user = Mock(id=999)
        mock_agent = Mock(spec=AgentConfig, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(AgentConfig.objects, "get", return_value=mock_agent),
            pytest.raises(CMSError, match=r"not found|access denied|permission"),
        ):
            services.get_agent(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, user):
        """Service propagates unexpected database errors."""
        with (
            patch.object(AgentConfig.objects, "get", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.get_agent(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.get_agent(agent_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.get_agent("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_agent(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - agent_id parameter
    # -------------------------------------------------------------------------

    def test_requires_agent_id_argument(self, user):
        """Service raises TypeError if agent_id not provided."""
        with pytest.raises(TypeError):
            services.get_agent(user)

    def test_raises_on_none_agent_id(self, user):
        """Service raises error if agent_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(user, None)

    def test_raises_on_invalid_agent_id_type(self, user):
        """Service raises error if agent_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(user, "not-an-id")

    def test_raises_on_negative_agent_id(self, user):
        """Service raises error if agent_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(user, -1)

    def test_logs_error_on_invalid_agent_id(self, user, caplog):
        """Service logs error when given invalid agent_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_agent(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of agent."""
        with patch.object(AgentConfig.objects, "get", return_value=None), pytest.raises(TypeError):
            services.get_agent(user, 42)

    def test_raises_on_model_returns_wrong_type(self, user):
        """Service raises TypeError if model returns wrong type."""
        with patch.object(AgentConfig.objects, "get", return_value="not an agent"), pytest.raises(TypeError):
            services.get_agent(user, 42)

    def test_raises_on_model_returns_dict(self, user):
        """Service raises TypeError if model returns dict instead of AgentConfig."""
        with patch.object(AgentConfig.objects, "get", return_value={"id": 42}), pytest.raises(TypeError):
            services.get_agent(user, 42)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch.object(AgentConfig.objects, "get", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_agent(user, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestCreateAgent:
    """Tests for create_agent() service function.

    Tests SERVICE behavior with mocked assets service layer:
    - Delegates to cms.assets.services.create_agent correctly
    - Returns what assets service returns
    - Logs all errors from downstream
    - Validates user input
    - Propagates errors from assets service
    """

    # -------------------------------------------------------------------------
    # Service delegates to assets service correctly
    # -------------------------------------------------------------------------

    def test_calls_assets_create_agent_with_kwargs(self, user):
        """Service delegates to cms.assets.services.create_agent with all kwargs."""
        mock_agent = Mock(spec=AgentConfig, id=42)
        with patch("cms.services.assets_create_agent", return_value=mock_agent) as mock_create:
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
            mock_create.assert_called_once_with(
                user=user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_passes_optional_upload_method_to_assets(self, user):
        """Service passes optional upload_method to assets service."""
        mock_agent = Mock(spec=AgentConfig, id=42)
        with patch("cms.services.assets_create_agent", return_value=mock_agent) as mock_create:
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
                upload_method="presigned",
            )
            mock_create.assert_called_once()
            _, kwargs = mock_create.call_args
            assert kwargs["upload_method"] == "presigned"

    # -------------------------------------------------------------------------
    # Service returns what assets service returns
    # -------------------------------------------------------------------------

    def test_returns_agent_from_assets_service(self, user):
        """Service returns agent returned by assets service."""
        mock_agent = Mock(spec=AgentConfig, id=42)
        mock_agent.configure_mock(name="Test Agent")
        with patch("cms.services.assets_create_agent", return_value=mock_agent):
            result = services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
            assert result.id == 42
            assert result.name == "Test Agent"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        mock_agent = Mock(spec=AgentConfig, id=42)
        with (
            patch("cms.services.assets_create_agent", return_value=mock_agent),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful creation."""
        mock_agent = Mock(spec=AgentConfig, id=42)
        with (
            patch("cms.services.assets_create_agent", return_value=mock_agent),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
        assert "42" in caplog.text  # agent id in log

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_assets_service_fails(self, user, caplog):
        """Service logs error when assets service raises exception."""
        from cms.assets.services import AssetError

        with (
            patch("cms.services.assets_create_agent", side_effect=AssetError("OS not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(AssetError),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="invalid-os",
                file_size=1000,
                sha256="abc123",
            )
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation - assets service errors
    # -------------------------------------------------------------------------

    def test_propagates_asset_error(self, user):
        """Service propagates AssetError from assets service."""
        from cms.assets.services import AssetError

        with (
            patch("cms.services.assets_create_agent", side_effect=AssetError("OS not found")),
            pytest.raises(AssetError, match="OS not found"),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="invalid-os",
                file_size=1000,
                sha256="abc123",
            )

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from assets service."""
        with (
            patch("cms.services.assets_create_agent", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.create_agent(
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_agent(
                None,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.create_agent(
                "not-a-user",
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.create_agent(
                unsaved_user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.create_agent(
                None,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Response validation - assets service returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_assets_returns_none(self, user):
        """Service raises TypeError if assets service returns None."""
        with patch("cms.services.assets_create_agent", return_value=None), pytest.raises(TypeError):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_raises_on_assets_returns_wrong_type(self, user):
        """Service raises TypeError if assets service returns wrong type."""
        with patch("cms.services.assets_create_agent", return_value="not an agent"), pytest.raises(TypeError):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )

    def test_logs_error_on_invalid_assets_response(self, user, caplog):
        """Service logs error when assets service returns invalid response."""
        with (
            patch("cms.services.assets_create_agent", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.create_agent(
                user,
                name="Test Agent",
                s3_key="agents/test/agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=1000,
                sha256="abc123",
            )
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestDeleteAgent:
    """Tests for delete_agent() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates user and agent_id
    - Verifies ownership before delegating
    - Delegates to cms.assets.services.delete_agent correctly
    - Returns None (void function)
    - Logs all errors from downstream
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_agent_to_verify_ownership(self, user):
        """Service calls get_agent to verify ownership."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent) as mock_get,
            patch("cms.services.assets_delete_agent"),
        ):
            services.delete_agent(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_calls_assets_delete_agent_with_agent(self, user):
        """Service delegates to cms.assets.services.delete_agent with agent."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent") as mock_delete,
        ):
            services.delete_agent(user, 42)
            mock_delete.assert_called_once_with(mock_agent)

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, user):
        """Service returns None on successful deletion."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent"),
        ):
            result = services.delete_agent(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and agent_id."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_agent(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful deletion."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_agent(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_agent_not_found(self, user, caplog):
        """Service logs error when get_agent raises CMSError."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_agent", side_effect=CMSError("not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.delete_agent(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_assets_service_fails(self, user, caplog):
        """Service logs error when assets service raises exception."""
        from cms.assets.services import AssetError

        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent", side_effect=AssetError("S3 delete failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(AssetError),
        ):
            services.delete_agent(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_agent_not_found(self, user):
        """Service raises CMSError when agent doesn't exist."""
        from cms.exceptions import CMSError

        with patch.object(services, "get_agent", side_effect=CMSError("not found")), pytest.raises(CMSError):
            services.delete_agent(user, 999)

    def test_raises_cms_error_when_not_owner(self, user):
        """Service raises CMSError when user doesn't own agent (via get_agent)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_agent", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.delete_agent(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - assets service errors
    # -------------------------------------------------------------------------

    def test_propagates_asset_error(self, user):
        """Service propagates AssetError from assets service."""
        from cms.assets.services import AssetError

        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent", side_effect=AssetError("S3 delete failed")),
            pytest.raises(AssetError, match="S3 delete failed"),
        ):
            services.delete_agent(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from assets service."""
        mock_agent = Mock(spec=AgentConfig, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_agent", return_value=mock_agent),
            patch("cms.services.assets_delete_agent", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.delete_agent(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.delete_agent(agent_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.delete_agent("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.delete_agent(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - agent_id parameter
    # -------------------------------------------------------------------------

    def test_requires_agent_id_argument(self, user):
        """Service raises TypeError if agent_id not provided."""
        with pytest.raises(TypeError):
            services.delete_agent(user)

    def test_raises_on_none_agent_id(self, user):
        """Service raises error if agent_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(user, None)

    def test_raises_on_invalid_agent_id_type(self, user):
        """Service raises error if agent_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(user, "not-an-id")

    def test_raises_on_negative_agent_id(self, user):
        """Service raises error if agent_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(user, -1)

    def test_logs_error_on_invalid_agent_id(self, user, caplog):
        """Service logs error when given invalid agent_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.delete_agent(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()
