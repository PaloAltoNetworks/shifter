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


class TestUploads:
    def test_initiate_upload(self):
        pytest.fail("Not implemented")

    def test_complete_upload(self):
        pytest.fail("Not implemented")

    def test_cancel_upload(self):
        pytest.fail("Not implemented")


class TestUserQuota:
    def test_get_storage_used(self):
        pytest.fail("Not implemented")


class TestScenarios:
    def test_list_scenarios(self):
        pytest.fail("Not implemented")
