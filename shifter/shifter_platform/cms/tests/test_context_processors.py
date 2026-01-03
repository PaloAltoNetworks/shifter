"""Tests for mission_control context processors.

These tests live in cms/tests because mission_control tests are temporarily
disabled, but the context processor uses cms.services.get_active_range.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db import DatabaseError

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestActiveRangeContextProcessor:
    """Tests for active_range context processor."""

    # ---------------------------------------------------------------------
    # Happy path - authenticated user with active range
    # ---------------------------------------------------------------------

    def test_returns_active_range_ref(self):
        """Returns RangeRef when user has an active range."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeRef

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_ref = RangeRef(
            range_id=1,
            user_id=42,
            status=RangeStatus.READY,
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_ref,
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is True
        assert result["active_range"] is mock_range_ref
        assert result["active_range"].status == RangeStatus.READY

    def test_returns_false_for_non_ready_range(self):
        """Returns has_active_range=False when range is not ready."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeRef

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_ref = RangeRef(
            range_id=1,
            user_id=42,
            status=RangeStatus.PROVISIONING,
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_ref,
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is mock_range_ref
        assert result["active_range"].status == RangeStatus.PROVISIONING

    def test_returns_none_when_no_active_range(self):
        """Returns None when user has no active range."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=None,
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    # ---------------------------------------------------------------------
    # Unauthenticated user
    # ---------------------------------------------------------------------

    def test_returns_none_for_unauthenticated_user(self):
        """Returns None when user is not authenticated."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = False

        result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    def test_does_not_call_service_for_unauthenticated_user(self):
        """Does not call get_active_range for unauthenticated user."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = False

        with patch(
            "mission_control.context_processors.get_active_range"
        ) as mock_get_active_range:
            active_range(mock_request)

        mock_get_active_range.assert_not_called()

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_handles_service_exception_gracefully(self):
        """Returns None when service raises exception."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with patch(
            "mission_control.context_processors.get_active_range",
            side_effect=DatabaseError("DB connection failed"),
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    def test_handles_type_error_gracefully(self):
        """Returns None when service raises TypeError."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with patch(
            "mission_control.context_processors.get_active_range",
            side_effect=TypeError("Invalid user"),
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    # ---------------------------------------------------------------------
    # Logging - verify logger methods are called
    # ---------------------------------------------------------------------

    def test_logs_info_when_range_found(self):
        """Logs INFO when active range is found."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeRef

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_ref = RangeRef(
            range_id=1,
            user_id=42,
            status=RangeStatus.READY,
        )

        with (
            patch("mission_control.context_processors.logger") as mock_logger,
            patch(
                "mission_control.context_processors.get_active_range",
                return_value=mock_range_ref,
            ),
        ):
            active_range(mock_request)

        # Verify logger.info was called with expected arguments
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "active_range" in call_args[0]
        assert 42 in call_args  # user_id in args

    def test_logs_info_when_no_range(self):
        """Logs INFO when no active range found."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with (
            patch("mission_control.context_processors.logger") as mock_logger,
            patch(
                "mission_control.context_processors.get_active_range",
                return_value=None,
            ),
        ):
            active_range(mock_request)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "no active range" in call_args[0]
        assert 42 in call_args

    def test_logs_error_on_exception(self):
        """Logs ERROR when exception occurs."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with (
            patch("mission_control.context_processors.logger") as mock_logger,
            patch(
                "mission_control.context_processors.get_active_range",
                side_effect=DatabaseError("DB connection failed"),
            ),
        ):
            active_range(mock_request)

        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args[0]
        assert "Error" in call_args[0]
        assert 42 in call_args

    # ---------------------------------------------------------------------
    # RangeRef status checks
    # ---------------------------------------------------------------------

    def test_uses_status_comparison_for_is_ready(self):
        """Uses RangeStatus comparison for determining ready state."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeRef

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        # Create RangeRef with READY status
        mock_range_ref = RangeRef(
            range_id=1,
            user_id=42,
            status=RangeStatus.READY,
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_ref,
        ):
            result = active_range(mock_request)

        # Verify has_active_range is True for READY status
        assert result["has_active_range"] is True
        assert result["active_range"].status == RangeStatus.READY

    def test_terminal_range_not_considered_active(self):
        """Terminal ranges (DESTROYED, FAILED) are not considered has_active_range."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeRef

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        for status in [RangeStatus.DESTROYED, RangeStatus.FAILED]:
            mock_range_ref = RangeRef(
                range_id=1,
                user_id=42,
                status=status,
            )

            with patch(
                "mission_control.context_processors.get_active_range",
                return_value=mock_range_ref,
            ):
                result = active_range(mock_request)

            assert result["has_active_range"] is False, f"Expected False for {status}"
            assert result["active_range"].status == status
