"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

from unittest.mock import Mock, patch

import pytest

from cms import services
from shared.constants import USER_CANNOT_BE_NONE


@pytest.fixture
def mock_user():
    """Mock user that passes _validate_user checks."""
    return Mock(pk=42, id=42)


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

    def test_calls_assets_get_storage_used_with_user(self, mock_user):
        """Service calls assets.get_storage_used with the user."""
        with patch("cms.assets.services.get_storage_used", return_value=0) as mock_storage:
            services.get_storage_used(mock_user)
            mock_storage.assert_called_once_with(mock_user)

    # --- Service returns what dependency returns ---

    def test_returns_zero_when_no_agents(self, mock_user):
        """Service returns 0 when user has no storage used."""
        with patch("cms.assets.services.get_storage_used", return_value=0):
            result = services.get_storage_used(mock_user)
            assert result == 0

    def test_returns_positive_value_when_agents_exist(self, mock_user):
        """Service returns positive value when user has agents."""
        expected_bytes = 1024 * 1024 * 5  # 5 MB
        with patch("cms.assets.services.get_storage_used", return_value=expected_bytes):
            result = services.get_storage_used(mock_user)
            assert result == expected_bytes

    def test_returns_large_value_for_many_agents(self, mock_user):
        """Service returns large value when user has many agents."""
        expected_bytes = 1024 * 1024 * 1024  # 1 GB
        with patch("cms.assets.services.get_storage_used", return_value=expected_bytes):
            result = services.get_storage_used(mock_user)
            assert result == expected_bytes

    def test_returns_int_type(self, mock_user):
        """Service returns int type."""
        with patch("cms.assets.services.get_storage_used", return_value=1000):
            result = services.get_storage_used(mock_user)
            assert isinstance(result, int)

    # --- Input validation ---

    def test_raises_type_error_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_storage_used(None)

    def test_raises_type_error_when_user_invalid_type(self):
        """Service raises TypeError when user is not a User instance."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.get_storage_used("not_a_user")

    def test_raises_value_error_when_user_unsaved(self):
        """Service raises ValueError when user has no ID."""
        unsaved_user = Mock(id=None)
        with pytest.raises(ValueError, match="user must be saved"):
            services.get_storage_used(unsaved_user)

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, mock_user):
        """Service propagates unexpected exceptions from assets service."""
        with (
            patch("cms.assets.services.get_storage_used", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.get_storage_used(mock_user)
