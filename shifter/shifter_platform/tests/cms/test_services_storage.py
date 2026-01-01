"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Logging (debug and error levels)
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import logging
from unittest.mock import patch

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
class TestGetStorageUsed:
    """Tests for get_storage_used() service function.

    Tests SERVICE behavior:
    - Calls cms.assets.services.get_storage_used correctly
    - Returns what underlying service returns
    - Logs appropriately
    - Validates input
    - Propagates errors
    """

    # --- Service calls dependency correctly ---

    def test_calls_assets_get_storage_used_with_user(self, user):
        """Service calls assets.get_storage_used with the user."""
        with patch("cms.assets.services.get_storage_used", return_value=0) as mock_storage:
            services.get_storage_used(user)
            mock_storage.assert_called_once_with(user)

    # --- Service returns what dependency returns ---

    def test_returns_zero_when_no_agents(self, user):
        """Service returns 0 when user has no storage used."""
        with patch("cms.assets.services.get_storage_used", return_value=0):
            result = services.get_storage_used(user)
            assert result == 0

    def test_returns_positive_value_when_agents_exist(self, user):
        """Service returns positive value when user has agents."""
        expected_bytes = 1024 * 1024 * 5  # 5 MB
        with patch("cms.assets.services.get_storage_used", return_value=expected_bytes):
            result = services.get_storage_used(user)
            assert result == expected_bytes

    def test_returns_large_value_for_many_agents(self, user):
        """Service returns large value when user has many agents."""
        expected_bytes = 1024 * 1024 * 1024  # 1 GB
        with patch("cms.assets.services.get_storage_used", return_value=expected_bytes):
            result = services.get_storage_used(user)
            assert result == expected_bytes

    def test_returns_int_type(self, user):
        """Service returns int type."""
        with patch("cms.assets.services.get_storage_used", return_value=1000):
            result = services.get_storage_used(user)
            assert isinstance(result, int)

    # --- Input validation ---

    def test_raises_type_error_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.get_storage_used(None)

    def test_raises_type_error_when_user_invalid_type(self):
        """Service raises TypeError when user is not a User instance."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.get_storage_used("not_a_user")

    def test_raises_value_error_when_user_unsaved(self, db):
        """Service raises ValueError when user has no ID."""
        unsaved_user = User(username="unsaved@example.com")
        with pytest.raises(ValueError, match="user must be saved"):
            services.get_storage_used(unsaved_user)

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_storage_used(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with storage info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=1000),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_storage_used(user)
        assert "1000" in caplog.text or "storage" in caplog.text.lower()

    def test_logs_error_when_user_none(self, caplog):
        """Service logs error when user is None."""
        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_storage_used(None)
        assert "None" in caplog.text

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from assets service."""
        with (
            patch("cms.assets.services.get_storage_used", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.get_storage_used(user)
