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
from mission_control.models import AgentConfig, OperatingSystem

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
        with patch.object(AgentConfig, "active_for_user", return_value=[]) as mock_active:
            services.list_agents(user)
            mock_active.assert_called_once_with(user)

    # --- Service returns what model returns ---

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when model returns empty queryset."""
        with patch.object(AgentConfig, "active_for_user", return_value=[]):
            result = services.list_agents(user)
            assert result == []

    def test_returns_one_agent_when_model_returns_one(self, user):
        """Service returns one agent when model returns one."""
        mock_agent = Mock(spec=AgentConfig, id=42, name="Mock Agent")
        with patch.object(AgentConfig, "active_for_user", return_value=[mock_agent]):
            result = services.list_agents(user)
            assert len(result) == 1
            assert result[0].id == 42

    def test_returns_five_agents_when_model_returns_five(self, user):
        """Service returns all agents model returns."""
        mock_agents = [Mock(spec=AgentConfig, id=i, name=f"Agent {i}") for i in range(5)]
        with patch.object(AgentConfig, "active_for_user", return_value=mock_agents):
            result = services.list_agents(user)
            assert len(result) == 5
            assert [a.id for a in result] == [0, 1, 2, 3, 4]

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch.object(AgentConfig, "active_for_user", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_agents(user)
        assert str(user.id) in caplog.text or user.email in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        mock_agents = [Mock(spec=AgentConfig) for _ in range(3)]
        with (
            patch.object(AgentConfig, "active_for_user", return_value=mock_agents),
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

    # --- Return type guarantee ---

    def test_returns_list_class_not_queryset(self, user):
        """Service returns list class, not QuerySet."""
        # Simulate QuerySet-like object
        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=AgentConfig)]))
        with patch.object(AgentConfig, "active_for_user", return_value=mock_qs):
            result = services.list_agents(user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, user):
        """Service returns list, not tuple even if model returns tuple."""
        mock_agent = Mock(spec=AgentConfig)
        with patch.object(AgentConfig, "active_for_user", return_value=(mock_agent,)):
            result = services.list_agents(user)
            assert type(result) is list

    def test_handles_generator_from_model(self, user):
        """Service converts generator to list."""

        def agent_generator():
            yield Mock(spec=AgentConfig)
            yield Mock(spec=AgentConfig)

        with patch.object(AgentConfig, "active_for_user", return_value=agent_generator()):
            result = services.list_agents(user)
            assert type(result) is list
            assert len(result) == 2

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


@pytest.mark.django_db
class TestListCredentials:
    """Tests for list_credentials() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_active_for_user_with_user(self, user):
        """Service calls Credential.active_for_user with the user."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=[]) as mock_active:
            services.list_credentials(user)
            mock_active.assert_called_once_with(user)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when model returns empty queryset."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=[]):
            result = services.list_credentials(user)
            assert result == []

    def test_returns_one_credential_when_model_returns_one(self, user):
        """Service returns one credential when model returns one."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42)
        mock_cred.configure_mock(name="Mock Credential")
        with patch.object(Credential, "active_for_user", return_value=[mock_cred]):
            result = services.list_credentials(user)
            assert len(result) == 1
            assert result[0].id == 42

    def test_returns_all_credentials_when_model_returns_multiple(self, user):
        """Service returns all credentials model returns."""
        from cms.models import Credential

        mock_creds = [Mock(spec=Credential, id=i) for i in range(5)]
        with patch.object(Credential, "active_for_user", return_value=mock_creds):
            result = services.list_credentials(user)
            assert len(result) == 5
            assert [c.id for c in result] == [0, 1, 2, 3, 4]

    def test_returns_both_credential_types(self, user):
        """Service returns both SCM and deployment profile credentials."""
        from cms.models import Credential

        mock_scm = Mock(spec=Credential, id=1, credential_type="scm")
        mock_dp = Mock(spec=Credential, id=2, credential_type="deployment_profile")
        with patch.object(Credential, "active_for_user", return_value=[mock_scm, mock_dp]):
            result = services.list_credentials(user)
            assert len(result) == 2
            types = {c.credential_type for c in result}
            assert types == {"scm", "deployment_profile"}

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_credentials(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        from cms.models import Credential

        mock_creds = [Mock(spec=Credential) for _ in range(3)]
        with (
            patch.object(Credential, "active_for_user", return_value=mock_creds),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_credentials(user)
        assert "3" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_on_downstream_exception(self, user, caplog):
        """Service logs error when model raises exception."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.list_credentials(user)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_model_exception(self, user):
        """Service propagates exceptions from model."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", side_effect=ValueError("Model error")),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_credentials(user)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of list."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=None), pytest.raises(TypeError):
            services.list_credentials(user)

    def test_raises_on_model_returns_string(self, user):
        """Service raises TypeError if model returns string instead of list."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value="not a list"), pytest.raises(TypeError):
            services.list_credentials(user)

    def test_raises_on_model_returns_list_of_wrong_type(self, user):
        """Service raises TypeError if model returns list of wrong type."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=[{"id": 1}, {"id": 2}]),
            pytest.raises(TypeError),
        ):
            services.list_credentials(user)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_credentials(user)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Return type guarantee
    # -------------------------------------------------------------------------

    def test_returns_list_class_not_queryset(self, user):
        """Service returns list class, not QuerySet."""
        from cms.models import Credential

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=Credential)]))
        with patch.object(Credential, "active_for_user", return_value=mock_qs):
            result = services.list_credentials(user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, user):
        """Service returns list, not tuple even if model returns tuple."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential)
        with patch.object(Credential, "active_for_user", return_value=(mock_cred,)):
            result = services.list_credentials(user)
            assert type(result) is list

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.list_credentials()

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.list_credentials(None)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.list_credentials("not-a-user")

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.list_credentials(unsaved_user)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.list_credentials(None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestGetCredential:
    """Tests for get_credential() service function.

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

    def test_calls_objects_get_with_credential_id(self, user):
        """Service queries Credential by id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with patch.object(Credential.objects, "get", return_value=mock_cred) as mock_get:
            services.get_credential(user, 42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_credential_when_found_and_owned(self, user):
        """Service returns credential when it exists and belongs to user."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with patch.object(Credential.objects, "get", return_value=mock_cred):
            result = services.get_credential(user, 42)
            assert result.id == 42

    def test_returns_credential_with_correct_attributes(self, user):
        """Service returns credential with all attributes intact."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None, credential_type="scm")
        mock_cred.configure_mock(name="Test Credential")
        with patch.object(Credential.objects, "get", return_value=mock_cred):
            result = services.get_credential(user, 42)
            assert result.name == "Test Credential"
            assert result.credential_type == "scm"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and credential_id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_credential(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful retrieval."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_credential(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_credential_not_found(self, user, caplog):
        """Service logs error when credential doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_credential_owned_by_other_user(self, user, caplog):
        """Service logs error when credential belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        other_user = Mock(id=999)
        mock_cred = Mock(spec=Credential, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "denied" in caplog.text.lower() or "owner" in caplog.text.lower()

    def test_logs_error_when_credential_is_deleted(self, user, caplog):
        """Service logs error when credential is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "deleted" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, user, caplog):
        """Service logs error when database raises exception."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for business logic failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_credential_not_found(self, user):
        """Service raises CMSError when credential doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 999)

    def test_raises_cms_error_when_credential_owned_by_other_user(self, user):
        """Service raises CMSError when credential belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        other_user = Mock(id=999)
        mock_cred = Mock(spec=Credential, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)

    def test_raises_cms_error_when_credential_is_deleted(self, user):
        """Service raises CMSError when credential is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, user):
        """CMSError message indicates credential not found."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_credential(user, 999)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, user):
        """Service propagates unexpected database errors."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.get_credential(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.get_credential(credential_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.get_credential("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_credential(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - credential_id parameter
    # -------------------------------------------------------------------------

    def test_requires_credential_id_argument(self, user):
        """Service raises TypeError if credential_id not provided."""
        with pytest.raises(TypeError):
            services.get_credential(user)

    def test_raises_on_none_credential_id(self, user):
        """Service raises error if credential_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, None)

    def test_raises_on_invalid_credential_id_type(self, user):
        """Service raises error if credential_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, "not-an-id")

    def test_raises_on_negative_credential_id(self, user):
        """Service raises error if credential_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, -1)

    def test_logs_error_on_invalid_credential_id(self, user, caplog):
        """Service logs error when given invalid credential_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_credential(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of credential."""
        from cms.models import Credential

        with patch.object(Credential.objects, "get", return_value=None), pytest.raises(TypeError):
            services.get_credential(user, 42)

    def test_raises_on_model_returns_wrong_type(self, user):
        """Service raises TypeError if model returns wrong type."""
        from cms.models import Credential

        with patch.object(Credential.objects, "get", return_value="not a credential"), pytest.raises(TypeError):
            services.get_credential(user, 42)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestCreateCredential:
    """Tests for create_credential() service function.

    Tests SERVICE behavior:
    - Creates correct credential type (SCM or deployment profile)
    - Validates required fields based on type
    - Logs activity on creation
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Create SCM credential
    # -------------------------------------------------------------------------

    def test_create_scm_credential_succeeds(self, user):
        """Service creates SCM credential with valid data."""
        from cms.models import Credential

        with patch.object(Credential, "save") as mock_save:
            result = services.create_credential(
                user,
                credential_type="scm",
                name="My SCM",
                scm_folder_name="test-folder",
                scm_pin_id="pin123",
                scm_pin_value="secret",
                sls_region="americas",
            )
            mock_save.assert_called_once()
            assert result.credential_type == "scm"

    def test_create_scm_credential_returns_credential(self, user):
        """Service returns the created credential."""
        from cms.models import Credential

        with patch.object(Credential, "save"):
            result = services.create_credential(
                user,
                credential_type="scm",
                name="My SCM",
                scm_folder_name="test-folder",
                scm_pin_id="pin123",
                scm_pin_value="secret",
                sls_region="americas",
            )
            assert isinstance(result, Credential)
            assert result.user == user

    # -------------------------------------------------------------------------
    # Create deployment profile
    # -------------------------------------------------------------------------

    def test_create_deployment_profile_succeeds(self, user):
        """Service creates deployment profile with valid data."""
        from cms.models import Credential

        with patch.object(Credential, "save") as mock_save:
            result = services.create_credential(
                user,
                credential_type="deployment_profile",
                name="My DP",
                authcode="D1234567",
            )
            mock_save.assert_called_once()
            assert result.credential_type == "deployment_profile"

    def test_create_deployment_profile_returns_credential(self, user):
        """Service returns the created deployment profile."""
        from cms.models import Credential

        with patch.object(Credential, "save"):
            result = services.create_credential(
                user,
                credential_type="deployment_profile",
                name="My DP",
                authcode="D1234567",
            )
            assert isinstance(result, Credential)
            assert result.authcode == "D1234567"

    # -------------------------------------------------------------------------
    # Input validation - credential_type
    # -------------------------------------------------------------------------

    def test_raises_on_invalid_credential_type(self, user):
        """Service raises error for invalid credential type."""
        with pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type="invalid_type",
                name="Test",
            )

    def test_raises_on_none_credential_type(self, user):
        """Service raises error if credential_type is None."""
        with pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type=None,
                name="Test",
            )

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.create_credential(
                credential_type="scm",
                name="Test",
            )

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_credential(
                None,
                credential_type="scm",
                name="Test",
            )

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        with pytest.raises((TypeError, ValueError)):
            services.create_credential(
                unsaved_user,
                credential_type="scm",
                name="Test",
            )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry."""
        from cms.models import Credential

        with (
            patch.object(Credential, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_credential(
                user,
                credential_type="deployment_profile",
                name="Test DP",
                authcode="D1234567",
            )
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful creation."""
        from cms.models import Credential

        with (
            patch.object(Credential, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_credential(
                user,
                credential_type="deployment_profile",
                name="Test DP",
                authcode="D1234567",
            )
        assert "deployment_profile" in caplog.text.lower() or "created" in caplog.text.lower()

    def test_logs_error_on_validation_failure(self, user, caplog):
        """Service logs error when validation fails."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type="invalid",
                name="Test",
            )
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestDeleteCredential:
    """Tests for delete_credential() service function.

    Tests SERVICE behavior:
    - Validates ownership before deletion
    - Performs soft delete
    - Logs activity
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and deletes
    # -------------------------------------------------------------------------

    def test_gets_credential_to_verify_ownership(self, user):
        """Service calls get_credential to verify ownership."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred) as mock_get,
            patch.object(mock_cred, "save"),
        ):
            services.delete_credential(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_soft_deletes_credential(self, user):
        """Service performs soft delete by setting deleted_at."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save") as mock_save,
        ):
            services.delete_credential(user, 42)
            assert mock_cred.deleted_at is not None
            mock_save.assert_called_once()

    def test_returns_none_on_success(self, user):
        """Service returns None on successful deletion."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
        ):
            result = services.delete_credential(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and credential_id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_credential(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful deletion."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_credential(user, 42)
        assert "42" in caplog.text

    def test_logs_error_when_credential_not_found(self, user, caplog):
        """Service logs error when get_credential raises CMSError."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_credential", side_effect=CMSError("not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.delete_credential(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_credential_not_found(self, user):
        """Service raises CMSError when credential doesn't exist."""
        from cms.exceptions import CMSError

        with patch.object(services, "get_credential", side_effect=CMSError("not found")), pytest.raises(CMSError):
            services.delete_credential(user, 999)

    def test_raises_cms_error_when_not_owner(self, user):
        """Service raises CMSError when user doesn't own credential (via get_credential)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_credential", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.delete_credential(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.delete_credential(user, 42)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.delete_credential(credential_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(None, 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(unsaved_user, 42)

    def test_raises_on_none_credential_id(self, user):
        """Service raises error if credential_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, None)

    def test_raises_on_invalid_credential_id_type(self, user):
        """Service raises error if credential_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, "not-an-id")

    def test_raises_on_negative_credential_id(self, user):
        """Service raises error if credential_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, -1)

    def test_logs_error_on_invalid_credential_id(self, user, caplog):
        """Service logs error when given invalid credential_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


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
        """Service queries Range by user."""
        with patch("cms.services.Range.objects.filter") as mock_filter:
            mock_filter.return_value = []
            services.list_ranges(user)
            mock_filter.assert_called_once_with(user=user)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when no ranges exist."""
        with patch("cms.services.Range.objects.filter") as mock_filter:
            mock_filter.return_value = []
            result = services.list_ranges(user)
            assert result == []

    def test_returns_one_range_when_model_returns_one(self, user):
        """Service returns one range when model returns one."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user, status="ready")
        with patch("cms.services.Range.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_range]
            result = services.list_ranges(user)
            assert len(result) == 1
            assert result[0].id == 42

    def test_returns_all_ranges_when_model_returns_multiple(self, user):
        """Service returns all ranges model returns."""
        from mission_control.models import Range

        mock_ranges = [Mock(spec=Range, id=i, user=user, status="ready") for i in range(5)]
        with patch("cms.services.Range.objects.filter") as mock_filter:
            mock_filter.return_value = mock_ranges
            result = services.list_ranges(user)
            assert len(result) == 5
            assert [r.id for r in result] == [0, 1, 2, 3, 4]

    def test_returns_ranges_of_all_statuses(self, user):
        """Service returns ranges regardless of status (no filtering)."""
        from mission_control.models import Range

        mock_ready = Mock(spec=Range, id=1, user=user, status="ready")
        mock_provisioning = Mock(spec=Range, id=2, user=user, status="provisioning")
        mock_destroyed = Mock(spec=Range, id=3, user=user, status="destroyed")
        with patch("cms.services.Range.objects.filter") as mock_filter:
            mock_filter.return_value = [mock_ready, mock_provisioning, mock_destroyed]
            result = services.list_ranges(user)
            assert len(result) == 3
            statuses = {r.status for r in result}
            assert statuses == {"ready", "provisioning", "destroyed"}

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch("cms.services.Range.objects.filter", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_ranges(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        from mission_control.models import Range

        mock_ranges = [Mock(spec=Range) for _ in range(3)]
        with (
            patch("cms.services.Range.objects.filter", return_value=mock_ranges),
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
            patch("cms.services.Range.objects.filter", side_effect=RuntimeError("DB connection failed")),
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
            patch("cms.services.Range.objects.filter", side_effect=ValueError("Model error")),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_ranges(user)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of list."""
        with patch("cms.services.Range.objects.filter", return_value=None), pytest.raises(TypeError):
            services.list_ranges(user)

    def test_raises_on_model_returns_string(self, user):
        """Service raises TypeError if model returns string instead of list."""
        with patch("cms.services.Range.objects.filter", return_value="not a list"), pytest.raises(TypeError):
            services.list_ranges(user)

    def test_raises_on_model_returns_list_of_wrong_type(self, user):
        """Service raises TypeError if model returns list of wrong type."""
        with (
            patch("cms.services.Range.objects.filter", return_value=[{"id": 1}, {"id": 2}]),
            pytest.raises(TypeError),
        ):
            services.list_ranges(user)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch("cms.services.Range.objects.filter", return_value=None),
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
        from mission_control.models import Range

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=Range)]))
        with patch("cms.services.Range.objects.filter", return_value=mock_qs):
            result = services.list_ranges(user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, user):
        """Service returns list, not tuple even if model returns tuple."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range)
        with patch("cms.services.Range.objects.filter", return_value=(mock_range,)):
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
        """Service queries Range by id."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with patch("cms.services.Range.objects.get", return_value=mock_range) as mock_get:
            services.get_range(user, 42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_range_when_found_and_owned(self, user):
        """Service returns range when it exists and belongs to user."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with patch("cms.services.Range.objects.get", return_value=mock_range):
            result = services.get_range(user, 42)
            assert result.id == 42

    def test_returns_range_with_correct_attributes(self, user):
        """Service returns range with all attributes intact."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user, status="ready", victim_ip="10.1.1.10")
        with patch("cms.services.Range.objects.get", return_value=mock_range):
            result = services.get_range(user, 42)
            assert result.status == "ready"
            assert result.victim_ip == "10.1.1.10"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch("cms.services.Range.objects.get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful retrieval."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch("cms.services.Range.objects.get", return_value=mock_range),
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
        from mission_control.models import Range

        with (
            patch("cms.services.Range.objects.get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_range_owned_by_other_user(self, user, caplog):
        """Service logs error when range belongs to different user."""
        from cms.exceptions import CMSError
        from mission_control.models import Range

        other_user = Mock(id=999)
        mock_range = Mock(spec=Range, id=42, user=other_user)
        with (
            patch("cms.services.Range.objects.get", return_value=mock_range),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 42)
        assert "error" in caplog.text.lower() or "denied" in caplog.text.lower() or "owner" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, user, caplog):
        """Service logs error when database raises exception."""
        with (
            patch("cms.services.Range.objects.get", side_effect=RuntimeError("DB connection failed")),
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
        from mission_control.models import Range

        with (
            patch("cms.services.Range.objects.get", side_effect=Range.DoesNotExist),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 999)

    def test_raises_cms_error_when_range_owned_by_other_user(self, user):
        """Service raises CMSError when range belongs to different user."""
        from cms.exceptions import CMSError
        from mission_control.models import Range

        other_user = Mock(id=999)
        mock_range = Mock(spec=Range, id=42, user=other_user)
        with (
            patch("cms.services.Range.objects.get", return_value=mock_range),
            pytest.raises(CMSError),
        ):
            services.get_range(user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, user):
        """CMSError message indicates range not found."""
        from cms.exceptions import CMSError
        from mission_control.models import Range

        with (
            patch("cms.services.Range.objects.get", side_effect=Range.DoesNotExist),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_range(user, 999)

    def test_cms_error_has_descriptive_message_for_ownership(self, user):
        """CMSError message indicates ownership violation."""
        from cms.exceptions import CMSError
        from mission_control.models import Range

        other_user = Mock(id=999)
        mock_range = Mock(spec=Range, id=42, user=other_user)
        with (
            patch("cms.services.Range.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match=r"not found|access denied|permission"),
        ):
            services.get_range(user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, user):
        """Service propagates unexpected database errors."""
        with (
            patch("cms.services.Range.objects.get", side_effect=Exception("DB connection failed")),
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
        with patch("cms.services.Range.objects.get", return_value=None), pytest.raises(TypeError):
            services.get_range(user, 42)

    def test_raises_on_model_returns_wrong_type(self, user):
        """Service raises TypeError if model returns wrong type."""
        with patch("cms.services.Range.objects.get", return_value="not a range"), pytest.raises(TypeError):
            services.get_range(user, 42)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        with (
            patch("cms.services.Range.objects.get", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_range(user, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestCreateRange:
    """Tests for create_range() service function.

    Tests SERVICE behavior with mocked engine service:
    - Delegates to engine.services.orchestration.launch correctly
    - Returns what engine service returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service delegates to engine service correctly
    # -------------------------------------------------------------------------

    def test_calls_engine_launch_with_args(self, user):
        """Service delegates to engine.services.orchestration.launch with correct args."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with patch("cms.services.engine_launch", return_value=mock_range) as mock_launch:
            services.create_range(user, scenario="basic", agent_id=10)
            mock_launch.assert_called_once_with(
                user=user,
                agent_id=10,
                scenario="basic",
                ngfw_enabled=False,
            )

    def test_passes_ngfw_enabled_to_engine(self, user):
        """Service passes ngfw_enabled flag to engine."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with patch("cms.services.engine_launch", return_value=mock_range) as mock_launch:
            services.create_range(user, scenario="basic", agent_id=10, ngfw_enabled=True)
            mock_launch.assert_called_once()
            _, kwargs = mock_launch.call_args
            assert kwargs["ngfw_enabled"] is True

    # -------------------------------------------------------------------------
    # Service returns what engine service returns
    # -------------------------------------------------------------------------

    def test_returns_range_from_engine_service(self, user):
        """Service returns range returned by engine service."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user, status="provisioning")
        with patch("cms.services.engine_launch", return_value=mock_range):
            result = services.create_range(user, scenario="basic", agent_id=10)
            assert result.id == 42
            assert result.status == "provisioning"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch("cms.services.engine_launch", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_range(user, scenario="basic", agent_id=10)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful creation."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch("cms.services.engine_launch", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_range(user, scenario="basic", agent_id=10)
        assert "42" in caplog.text  # range id in log

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_engine_service_fails(self, user, caplog):
        """Service logs error when engine service raises exception."""
        from engine.services.orchestration import OrchestrationError

        with (
            patch("cms.services.engine_launch", side_effect=OrchestrationError("Already have active range")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(OrchestrationError),
        ):
            services.create_range(user, scenario="basic", agent_id=10)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    def test_propagates_orchestration_error(self, user):
        """Service propagates OrchestrationError from engine service."""
        from engine.services.orchestration import OrchestrationError

        with (
            patch("cms.services.engine_launch", side_effect=OrchestrationError("Already have active range")),
            pytest.raises(OrchestrationError, match="Already have active range"),
        ):
            services.create_range(user, scenario="basic", agent_id=10)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from engine service."""
        with (
            patch("cms.services.engine_launch", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.create_range(user, scenario="basic", agent_id=10)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.create_range(scenario="basic", agent_id=10)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(None, scenario="basic", agent_id=10)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.create_range("not-a-user", scenario="basic", agent_id=10)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.create_range(unsaved_user, scenario="basic", agent_id=10)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.create_range(None, scenario="basic", agent_id=10)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - agent_id parameter
    # -------------------------------------------------------------------------

    def test_requires_agent_id_argument(self, user):
        """Service raises TypeError if agent_id not provided."""
        with pytest.raises(TypeError):
            services.create_range(user, scenario="basic")

    def test_raises_on_none_agent_id(self, user):
        """Service raises error if agent_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(user, scenario="basic", agent_id=None)

    def test_raises_on_invalid_agent_id_type(self, user):
        """Service raises error if agent_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(user, scenario="basic", agent_id="not-an-id")

    def test_raises_on_negative_agent_id(self, user):
        """Service raises error if agent_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(user, scenario="basic", agent_id=-1)

    # -------------------------------------------------------------------------
    # Input validation - scenario parameter
    # -------------------------------------------------------------------------

    def test_requires_scenario_argument(self, user):
        """Service raises TypeError if scenario not provided."""
        with pytest.raises(TypeError):
            services.create_range(user, agent_id=10)

    def test_raises_on_none_scenario(self, user):
        """Service raises error if scenario is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(user, scenario=None, agent_id=10)

    def test_raises_on_empty_scenario(self, user):
        """Service raises error if scenario is empty string."""
        with pytest.raises((TypeError, ValueError)):
            services.create_range(user, scenario="", agent_id=10)

    # -------------------------------------------------------------------------
    # Response validation - engine returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_engine_returns_none(self, user):
        """Service raises TypeError if engine service returns None."""
        with patch("cms.services.engine_launch", return_value=None), pytest.raises(TypeError):
            services.create_range(user, scenario="basic", agent_id=10)

    def test_raises_on_engine_returns_wrong_type(self, user):
        """Service raises TypeError if engine service returns wrong type."""
        with patch("cms.services.engine_launch", return_value="not a range"), pytest.raises(TypeError):
            services.create_range(user, scenario="basic", agent_id=10)

    def test_logs_error_on_invalid_engine_response(self, user, caplog):
        """Service logs error when engine service returns invalid response."""
        with (
            patch("cms.services.engine_launch", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.create_range(user, scenario="basic", agent_id=10)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Delegates to engine.services.orchestration.destroy correctly
    - Returns None (void function)
    - Logs all errors from downstream
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, user):
        """Service calls get_range to verify ownership."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_destroy"),
        ):
            services.destroy_range(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_calls_engine_destroy_with_user(self, user):
        """Service delegates to engine.services.orchestration.destroy with user."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy") as mock_destroy,
        ):
            services.destroy_range(user, 42)
            mock_destroy.assert_called_once_with(user)

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, user):
        """Service returns None on successful destruction."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy"),
        ):
            result = services.destroy_range(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.destroy_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful destruction."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy"),
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
        from engine.services.orchestration import OrchestrationError
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy", side_effect=OrchestrationError("No range to destroy")),
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
        from engine.services.orchestration import OrchestrationError
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy", side_effect=OrchestrationError("No range to destroy")),
            pytest.raises(OrchestrationError, match="No range to destroy"),
        ):
            services.destroy_range(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from engine service."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_destroy", side_effect=Exception("DB connection failed")),
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
    - Delegates to engine.services.orchestration.cancel correctly
    - Returns None (void function)
    - Logs all errors from downstream
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, user):
        """Service calls get_range to verify ownership."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_cancel"),
        ):
            services.cancel_range(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_calls_engine_cancel_with_user(self, user):
        """Service delegates to engine.services.orchestration.cancel with user."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel") as mock_cancel,
        ):
            services.cancel_range(user, 42)
            mock_cancel.assert_called_once_with(user)

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, user):
        """Service returns None on successful cancellation."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel"),
        ):
            result = services.cancel_range(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and range_id."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_range(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful cancellation."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel"),
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
        from engine.services.orchestration import OrchestrationError
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel", side_effect=OrchestrationError("Cannot cancel range")),
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
        from engine.services.orchestration import OrchestrationError
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel", side_effect=OrchestrationError("Cannot cancel range")),
            pytest.raises(OrchestrationError, match="Cannot cancel range"),
        ):
            services.cancel_range(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from engine service."""
        from mission_control.models import Range

        mock_range = Mock(spec=Range, id=42, user=user)
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel", side_effect=Exception("DB connection failed")),
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


# =============================================================================
# Upload Services
# =============================================================================


@pytest.mark.django_db
class TestInitiateUpload:
    """Tests for initiate_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, name, filename, file_size)
    - Checks storage quota
    - Validates file extension
    - Generates presigned URL via S3 service
    - Generates upload token
    - Returns dict with presigned_url, s3_key, upload_token, expected_os
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_get_storage_used_with_user(self, user):
        """Service calls get_storage_used to check quota."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0) as mock_storage,
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_storage.assert_called_once_with(user)

    def test_calls_validate_file_extension_with_filename(self, user):
        """Service calls validate_file_extension with the filename."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_validate.assert_called_once_with("agent.msi")

    def test_calls_generate_presigned_url_with_user_and_filename(self, user):
        """Service calls generate_presigned_upload_url with user_id and filename."""
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", "key")) as mock_presign,
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_presign.assert_called_once_with(user_id=user.id, filename="agent.msi")

    def test_calls_generate_upload_token_with_all_params(self, user):
        """Service calls generate_upload_token with all required params."""
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        token_path = "mission_control.services.upload_token.generate_upload_token"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("presigned_url", "s3_key")),
            patch(token_path, return_value="token") as mock_token,
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "My Agent", "agent.msi", 5000)
            mock_token.assert_called_once_with(
                user_id=user.id,
                s3_key="s3_key",
                name="My Agent",
                filename="agent.msi",
                os_slug="windows",
                file_size=5000,
            )

    # --- Service returns correct dict ---

    def test_returns_dict_with_presigned_url(self, user):
        """Service returns dict containing presigned_url."""
        presign_url = "https://s3.example.com/upload"
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=(presign_url, "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["presigned_url"] == presign_url

    def test_returns_dict_with_s3_key(self, user):
        """Service returns dict containing s3_key."""
        s3_key = "agents/1/abc123_agent.msi"
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", s3_key)),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["s3_key"] == s3_key

    def test_returns_dict_with_upload_token(self, user):
        """Service returns dict containing upload_token."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="signed_token_abc123"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["upload_token"] == "signed_token_abc123"

    def test_returns_dict_with_expected_os(self, user):
        """Service returns dict containing expected_os from file format."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="linux-debian")
            result = services.initiate_upload(user, "Agent", "agent.deb", 1000)
            assert result["expected_os"] == "linux-debian"

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.initiate_upload(None, "Agent", "agent.msi", 1000)

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        invalid_user = "not a user"
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.initiate_upload(invalid_user, "Agent", "agent.msi", 1000)

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved (id=None)."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.initiate_upload(unsaved_user, "Agent", "agent.msi", 1000)

    # --- Input validation - name ---

    def test_raises_valueerror_when_name_is_none(self, user):
        """Service raises ValueError when name is None."""
        with pytest.raises(ValueError, match="name cannot be None"):
            services.initiate_upload(user, None, "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_empty(self, user):
        """Service raises ValueError when name is empty string."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(user, "", "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_whitespace(self, user):
        """Service raises ValueError when name is only whitespace."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(user, "   ", "agent.msi", 1000)

    # --- Input validation - filename ---

    def test_raises_valueerror_when_filename_is_none(self, user):
        """Service raises ValueError when filename is None."""
        with pytest.raises(ValueError, match="filename cannot be None"):
            services.initiate_upload(user, "Agent", None, 1000)

    def test_raises_valueerror_when_filename_is_empty(self, user):
        """Service raises ValueError when filename is empty string."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(user, "Agent", "", 1000)

    def test_raises_valueerror_when_filename_is_whitespace(self, user):
        """Service raises ValueError when filename is only whitespace."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(user, "Agent", "   ", 1000)

    # --- Input validation - file_size ---

    def test_raises_typeerror_when_file_size_is_none(self, user):
        """Service raises TypeError when file_size is None."""
        with pytest.raises(TypeError, match="file_size cannot be None"):
            services.initiate_upload(user, "Agent", "agent.msi", None)

    def test_raises_typeerror_when_file_size_is_string(self, user):
        """Service raises TypeError when file_size is not an int."""
        with pytest.raises(TypeError, match="file_size must be an int"):
            services.initiate_upload(user, "Agent", "agent.msi", "1000")

    def test_raises_valueerror_when_file_size_is_zero(self, user):
        """Service raises ValueError when file_size is zero."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(user, "Agent", "agent.msi", 0)

    def test_raises_valueerror_when_file_size_is_negative(self, user):
        """Service raises ValueError when file_size is negative."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(user, "Agent", "agent.msi", -100)

    # --- Quota validation ---

    def test_raises_cmserror_when_quota_exceeded(self, user, settings):
        """Service raises CMSError when storage quota would be exceeded."""
        from cms.exceptions import CMSError

        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 9 * 1024 * 1024  # 9 MB used
        new_file_size = 2 * 1024 * 1024  # 2 MB new file

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            pytest.raises(CMSError, match="quota exceeded"),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", new_file_size)

    def test_succeeds_when_quota_not_exceeded(self, user, settings):
        """Service succeeds when storage quota is not exceeded."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 4 * 1024 * 1024  # 4 MB new file (under 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    def test_succeeds_when_quota_exactly_met(self, user, settings):
        """Service succeeds when storage quota is exactly met."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 5 * 1024 * 1024  # 5 MB new file (exactly 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    # --- File extension validation ---

    def test_raises_cmserror_on_invalid_extension(self, user):
        """Service raises CMSError when file extension is not allowed."""
        from cms.exceptions import CMSError
        from mission_control.services.validation import ValidationError

        validation_path = "mission_control.services.validation.validate_file_extension"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch(validation_path, side_effect=ValidationError("Extension not allowed")),
            pytest.raises(CMSError, match="Extension not allowed"),
        ):
            services.initiate_upload(user, "Agent", "agent.exe", 1000)

    # --- S3 error handling ---

    def test_raises_cmserror_on_s3_error(self, user):
        """Service raises CMSError when S3 presigned URL generation fails."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", side_effect=S3Error("S3 unavailable")),
            pytest.raises(CMSError, match="Failed to initiate upload"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with file info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert "agent.msi" in caplog.text or "success" in caplog.text.lower()

    def test_logs_error_on_quota_exceeded(self, user, caplog, settings):
        """Service logs error when quota is exceeded."""
        from cms.exceptions import CMSError

        settings.AGENT_USER_STORAGE_QUOTA_MB = 1
        with (
            patch("cms.assets.services.get_storage_used", return_value=2 * 1024 * 1024),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert "quota" in caplog.text.lower() or "exceeded" in caplog.text.lower()

    def test_logs_error_on_validation_failure(self, user, caplog):
        """Service logs error when file extension validation fails."""
        from cms.exceptions import CMSError
        from mission_control.services.validation import ValidationError

        validation_path = "mission_control.services.validation.validate_file_extension"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch(validation_path, side_effect=ValidationError("Invalid extension")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.initiate_upload(user, "Agent", "agent.exe", 1000)
        assert "error" in caplog.text.lower() or "extension" in caplog.text.lower()

    def test_logs_error_on_input_validation_failure(self, user, caplog):
        """Service logs error when input validation fails."""
        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(ValueError),
        ):
            services.initiate_upload(user, "", "agent.msi", 1000)
        assert "error" in caplog.text.lower() or "name" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("cms.assets.services.get_storage_used", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", 1000)


@pytest.mark.django_db
class TestCompleteUpload:
    """Tests for complete_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, upload_token, sha256)
    - Verifies upload token
    - Verifies S3 object exists
    - Tags S3 object as completed
    - Creates agent record
    - Returns created agent
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_verify_upload_token_with_token_and_user_id(self, user):
        """Service calls verify_upload_token with the token and user_id."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload) as mock_verify,
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_verify.assert_called_once_with("token123", user.id)

    def test_calls_verify_s3_object_exists_with_s3_key(self, user):
        """Service calls verify_s3_object_exists with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")) as mock_verify_s3,
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_verify_s3.assert_called_once_with("agents/1/abc_agent.msi")

    def test_calls_tag_s3_object_with_completed_tags(self, user):
        """Service calls tag_s3_object with completion tags."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object") as mock_tag,
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_tag.assert_called_once_with("agents/1/abc_agent.msi", {"status": "completed"})

    def test_calls_create_agent_with_all_params(self, user):
        """Service calls create_agent with all required params."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "My Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 5000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(5000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_create.assert_called_once_with(
                user=user,
                name="My Agent",
                s3_key="agents/1/abc_agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=5000,
                sha256="sha256hash",
                upload_method="presigned",
            )

    # --- Service returns agent ---

    def test_returns_created_agent(self, user):
        """Service returns the agent created by create_agent."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        mock_agent = Mock(spec=AgentConfig, id=42, name="Agent")
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent", return_value=mock_agent),
        ):
            result = services.complete_upload(user, "token123", "sha256hash")
            assert result == mock_agent
            assert result.id == 42

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.complete_upload(None, "token123", "sha256hash")

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.complete_upload("not a user", "token123", "sha256hash")

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.complete_upload(unsaved_user, "token123", "sha256hash")

    # --- Input validation - upload_token ---

    def test_raises_valueerror_when_upload_token_is_none(self, user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.complete_upload(user, None, "sha256hash")

    def test_raises_valueerror_when_upload_token_is_empty(self, user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(user, "", "sha256hash")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(user, "   ", "sha256hash")

    # --- Input validation - sha256 ---

    def test_raises_valueerror_when_sha256_is_none(self, user):
        """Service raises ValueError when sha256 is None."""
        with pytest.raises(ValueError, match="sha256 cannot be None"):
            services.complete_upload(user, "token123", None)

    def test_raises_valueerror_when_sha256_is_empty(self, user):
        """Service raises ValueError when sha256 is empty."""
        with pytest.raises(ValueError, match="sha256 cannot be empty"):
            services.complete_upload(user, "token123", "")

    def test_raises_valueerror_when_sha256_is_whitespace(self, user):
        """Service raises ValueError when sha256 is only whitespace."""
        with pytest.raises(ValueError, match="sha256 cannot be empty"):
            services.complete_upload(user, "token123", "   ")

    # --- Token verification errors ---

    def test_raises_cmserror_on_invalid_token(self, user):
        """Service raises CMSError when token is invalid."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid token")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(user, "bad_token", "sha256hash")

    def test_raises_cmserror_on_expired_token(self, user):
        """Service raises CMSError when token is expired."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Token expired")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(user, "expired_token", "sha256hash")

    # --- S3 verification errors ---

    def test_raises_cmserror_when_s3_object_not_found(self, user):
        """Service raises CMSError when S3 object doesn't exist."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", side_effect=S3Error("Object not found")),
            pytest.raises(CMSError, match="Upload not found"),
        ):
            services.complete_upload(user, "token123", "sha256hash")

    def test_raises_cmserror_when_file_size_mismatch(self, user):
        """Service raises CMSError when S3 object size doesn't match token."""
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(5000, "etag")),  # Wrong size
            pytest.raises(CMSError, match="size mismatch"),
        ):
            services.complete_upload(user, "token123", "sha256hash")

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with agent info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
        assert "42" in caplog.text or "completed" in caplog.text.lower()

    def test_logs_error_on_invalid_token(self, user, caplog):
        """Service logs error when token verification fails."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.complete_upload(user, "bad_token", "sha256hash")
        assert "error" in caplog.text.lower() or "token" in caplog.text.lower()

    def test_logs_error_on_s3_verification_failure(self, user, caplog):
        """Service logs error when S3 verification fails."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", side_effect=S3Error("Not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.complete_upload(user, "token123", "sha256hash")
        assert "error" in caplog.text.lower() or "s3" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.complete_upload(user, "token123", "sha256hash")


@pytest.mark.django_db
class TestCancelUpload:
    """Tests for cancel_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, upload_token)
    - Verifies upload token
    - Deletes S3 object
    - Returns None on success
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_verify_upload_token_with_token_and_user_id(self, user):
        """Service calls verify_upload_token with the token and user_id."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload) as mock_verify,
            patch("mission_control.services.s3.delete_agent"),
        ):
            services.cancel_upload(user, "token123")
            mock_verify.assert_called_once_with("token123", user.id)

    def test_calls_delete_agent_with_s3_key(self, user):
        """Service calls delete_agent with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload),
            patch("mission_control.services.s3.delete_agent") as mock_delete,
        ):
            services.cancel_upload(user, "token123")
            mock_delete.assert_called_once_with("agents/1/abc_agent.msi")

    # --- Service returns None ---

    def test_returns_none_on_success(self, user):
        """Service returns None on successful cancellation."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
        ):
            result = services.cancel_upload(user, "token123")
            assert result is None

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.cancel_upload(None, "token123")

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.cancel_upload("not a user", "token123")

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.cancel_upload(unsaved_user, "token123")

    # --- Input validation - upload_token ---

    def test_raises_valueerror_when_upload_token_is_none(self, user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.cancel_upload(user, None)

    def test_raises_valueerror_when_upload_token_is_empty(self, user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(user, "")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(user, "   ")

    # --- Token verification errors ---

    def test_raises_cmserror_on_invalid_token(self, user):
        """Service raises CMSError when token is invalid."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid token")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.cancel_upload(user, "bad_token")

    def test_raises_cmserror_on_expired_token(self, user):
        """Service raises CMSError when token is expired."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Token expired")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.cancel_upload(user, "expired_token")

    # --- S3 delete errors (should be ignored) ---

    def test_succeeds_when_s3_delete_fails(self, user):
        """Service succeeds even when S3 delete fails (best effort cleanup)."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Delete failed")),
        ):
            # Should not raise - S3 delete is best effort
            result = services.cancel_upload(user, "token123")
            assert result is None

    def test_succeeds_when_s3_object_not_found(self, user):
        """Service succeeds when S3 object doesn't exist (already deleted)."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Object not found")),
        ):
            # Should not raise - object may have never been uploaded
            result = services.cancel_upload(user, "token123")
            assert result is None

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert "cancelled" in caplog.text.lower() or "cancel" in caplog.text.lower()

    def test_logs_warning_on_s3_delete_failure(self, user, caplog):
        """Service logs warning when S3 delete fails."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Delete failed")),
            caplog.at_level(logging.WARNING, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert "warning" in caplog.text.lower() or "failed" in caplog.text.lower() or "s3" in caplog.text.lower()

    def test_logs_error_on_invalid_token(self, user, caplog):
        """Service logs error when token verification fails."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.cancel_upload(user, "bad_token")
        assert "error" in caplog.text.lower() or "token" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.cancel_upload(user, "token123")


class TestUserQuota:
    def test_get_storage_used(self):
        pytest.fail("Not implemented")


class TestScenarios:
    def test_list_scenarios(self):
        pytest.fail("Not implemented")
