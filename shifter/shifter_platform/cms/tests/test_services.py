"""Tests for CMS services."""

import logging
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestGetActiveRange:
    """Tests for get_active_range service."""

    # ---------------------------------------------------------------------
    # Happy path
    # ---------------------------------------------------------------------

    def test_returns_active_range(self):
        """Returns RangeContext for non-deleted, non-terminal range."""
        from cms.models import RangeInstance
        from cms.services import get_active_range
        from shared.schemas import RangeContext

        user = MagicMock()
        user.id = 42

        # Create an active range
        RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        result = get_active_range(user)

        assert result is not None
        assert isinstance(result, RangeContext)
        assert result.range_id == 1
        assert result.user_id == 42
        assert result.status == RangeStatus.READY

    def test_returns_provisioning_range(self):
        """Returns RangeContext for range in PROVISIONING status."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        RangeInstance.objects.create(
            range_id=2,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        result = get_active_range(user)

        assert result is not None
        assert result.range_id == 2
        assert result.status == RangeStatus.PROVISIONING

    def test_returns_none_when_no_ranges(self):
        """Returns None when user has no ranges."""
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 999

        result = get_active_range(user)

        assert result is None

    # ---------------------------------------------------------------------
    # Filtering behavior
    # ---------------------------------------------------------------------

    def test_excludes_deleted_ranges(self):
        """Does not return soft-deleted ranges."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        # Create only a deleted range
        RangeInstance.objects.create(
            range_id=3,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
            deleted_at=timezone.now(),
        )

        result = get_active_range(user)

        assert result is None

    def test_excludes_destroyed_ranges(self):
        """Does not return ranges with DESTROYED status."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        RangeInstance.objects.create(
            range_id=4,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.DESTROYED.value,
        )

        result = get_active_range(user)

        assert result is None

    def test_excludes_failed_ranges(self):
        """Does not return ranges with FAILED status."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        RangeInstance.objects.create(
            range_id=5,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.FAILED.value,
        )

        result = get_active_range(user)

        assert result is None

    def test_returns_most_recent_active_range(self):
        """Returns RangeContext for the most recently created active range."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        # Create two active ranges with different range_ids
        RangeInstance.objects.create(
            range_id=10,
            scenario_id="old",
            user_id=42,
            status=RangeStatus.READY.value,
        )
        RangeInstance.objects.create(
            range_id=11,
            scenario_id="new",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        result = get_active_range(user)

        # Should return the most recent one (identified by range_id)
        assert result is not None
        assert result.range_id == 11

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_raises_type_error_for_none_user(self):
        """Raises TypeError when user is None."""
        from cms.services import get_active_range

        with pytest.raises(TypeError, match="user cannot be None"):
            get_active_range(None)

    def test_raises_type_error_for_invalid_user(self):
        """Raises TypeError when user lacks id attribute."""
        from cms.services import get_active_range

        with pytest.raises(TypeError, match="user must be a User instance"):
            get_active_range("not a user")

    # ---------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------

    def test_logs_debug_on_success(self, caplog):
        """Logs DEBUG when active range found."""
        from cms.models import RangeInstance
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        RangeInstance.objects.create(
            range_id=20,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        with caplog.at_level(logging.DEBUG, logger="cms.services"):
            get_active_range(user)

        assert "get_active_range" in caplog.text
        assert "found range_id=20" in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_when_no_range_found(self, caplog):
        """Logs DEBUG when no active range exists."""
        from cms.services import get_active_range

        user = MagicMock()
        user.id = 999

        with caplog.at_level(logging.DEBUG, logger="cms.services"):
            get_active_range(user)

        assert "get_active_range" in caplog.text
        assert "no active range" in caplog.text
        assert "999" in caplog.text

    def test_logs_error_on_none_user(self, caplog):
        """Logs ERROR when user is None."""
        from cms.services import get_active_range

        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises(TypeError):
            get_active_range(None)

        assert "get_active_range called with None" in caplog.text

    def test_logs_error_on_invalid_user_type(self, caplog):
        """Logs ERROR when user is invalid type."""
        from cms.services import get_active_range

        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises(TypeError):
            get_active_range("not a user")

        assert "get_active_range called with invalid user type" in caplog.text
        assert "str" in caplog.text

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_propagates_database_error(self):
        """Propagates database errors to caller."""
        from unittest.mock import patch

        from django.db import DatabaseError

        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        with (
            patch("cms.services.RangeInstance.active") as mock_active,
            pytest.raises(DatabaseError, match="DB connection failed"),
        ):
            mock_active.filter.side_effect = DatabaseError("DB connection failed")
            get_active_range(user)

    def test_logs_exception_on_database_error(self, caplog):
        """Logs exception when database error occurs."""
        from unittest.mock import patch

        from django.db import DatabaseError

        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            patch("cms.services.RangeInstance.active") as mock_active,
            pytest.raises(DatabaseError),
        ):
            mock_active.filter.side_effect = DatabaseError("DB connection failed")
            get_active_range(user)

        assert "Error in get_active_range" in caplog.text
        assert "42" in caplog.text

    # ---------------------------------------------------------------------
    # Validation - RangeContext validates on creation
    # ---------------------------------------------------------------------

    def test_validates_range_context_on_creation(self):
        """RangeContext validates data (range_id must be positive)."""
        from unittest.mock import patch

        from pydantic import ValidationError

        from cms.services import get_active_range

        user = MagicMock()
        user.id = 42

        # Create a mock instance with invalid range_id
        mock_instance = MagicMock()
        mock_instance.range_id = 0  # Invalid: must be positive
        mock_instance.user_id = 42
        mock_instance.status = RangeStatus.READY.value

        mock_queryset = MagicMock()
        mock_queryset.order_by.return_value.first.return_value = mock_instance

        with (
            patch("cms.services.RangeInstance.active") as mock_active,
            pytest.raises(ValidationError, match="range_id"),
        ):
            mock_active.filter.return_value = mock_queryset
            get_active_range(user)
