"""Tests for mission_control context processors."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.db import DatabaseError

from shared.enums import ResourceStatus


@pytest.mark.django_db
class TestActiveRangeContextProcessor:
    """Tests for active_range context processor."""

    # ---------------------------------------------------------------------
    # Happy path - authenticated user with active range
    # ---------------------------------------------------------------------

    def test_returns_active_range_context(self):
        """Returns RangeContext when user has an active range."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_context = RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=42,
            scenario_id="basic",
            status=ResourceStatus.READY,
            instances=[],
            agent_name="Test Agent",
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_context,
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is True
        assert result["active_range"] is mock_range_context
        assert result["active_range"].status == ResourceStatus.READY

    def test_returns_false_for_non_ready_range(self):
        """Returns has_active_range=False when range is not ready."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_context = RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=42,
            scenario_id="basic",
            status=ResourceStatus.PROVISIONING,
            instances=[],
            agent_name="Test Agent",
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_context,
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is mock_range_context
        assert result["active_range"].status == ResourceStatus.PROVISIONING

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

        with patch("mission_control.context_processors.get_active_range") as mock_get_active_range:
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

    def test_handles_invalid_return_type_gracefully(self):
        """Returns None when service returns invalid type (not RangeContext)."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        # Return a dict instead of RangeContext
        with patch(
            "mission_control.context_processors.get_active_range",
            return_value={"range_id": 1, "status": "ready"},
        ):
            result = active_range(mock_request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    def test_logs_error_on_invalid_return_type(self):
        """Logs ERROR when service returns invalid type."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        with (
            patch("mission_control.context_processors.logger") as mock_logger,
            patch(
                "mission_control.context_processors.get_active_range",
                return_value="not a RangeContext",
            ),
        ):
            active_range(mock_request)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0]
        assert "invalid type" in call_args[0]
        assert "str" in call_args  # type name in args

    # ---------------------------------------------------------------------
    # Logging - verify logger methods are called
    # ---------------------------------------------------------------------

    def test_logs_info_when_range_found(self):
        """Logs INFO when active range is found."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        mock_range_context = RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=42,
            scenario_id="basic",
            status=ResourceStatus.READY,
            instances=[],
            agent_name="Test Agent",
        )

        with (
            patch("mission_control.context_processors.logger") as mock_logger,
            patch(
                "mission_control.context_processors.get_active_range",
                return_value=mock_range_context,
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
    # RangeContext status checks
    # ---------------------------------------------------------------------

    def test_uses_is_ready_property(self):
        """Uses RangeContext.is_ready property for determining ready state."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        # Create RangeContext with READY status
        mock_range_context = RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=42,
            scenario_id="basic",
            status=ResourceStatus.READY,
            instances=[],
            agent_name="Test Agent",
        )

        with patch(
            "mission_control.context_processors.get_active_range",
            return_value=mock_range_context,
        ):
            result = active_range(mock_request)

        # Verify has_active_range is True for READY status
        assert result["has_active_range"] is True
        assert result["active_range"].status == ResourceStatus.READY
        assert result["active_range"].is_ready is True

    def test_terminal_range_not_considered_active(self):
        """Terminal ranges (DESTROYED, FAILED) are not considered has_active_range."""
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        for status in [ResourceStatus.DESTROYED, ResourceStatus.FAILED]:
            mock_range_context = RangeContext(
                request_id=uuid4(),
                range_id=1,
                user_id=42,
                scenario_id="basic",
                status=status,
                instances=[],
                agent_name="Test Agent",
            )

            with patch(
                "mission_control.context_processors.get_active_range",
                return_value=mock_range_context,
            ):
                result = active_range(mock_request)

            assert result["has_active_range"] is False, f"Expected False for {status}"
            assert result["active_range"].status == status
            assert result["active_range"].is_ready is False

    # ---------------------------------------------------------------------
    # CTF participant instance filtering
    # ---------------------------------------------------------------------

    @staticmethod
    def _make_range_with_instances(os_types):
        """Create a RangeContext with instances of the given os_types."""
        from shared.schemas import InstanceContext, RangeContext

        instances = [
            InstanceContext(uuid=str(uuid4()), name=os, os_type=os, role="attacker" if os == "kali" else "victim")
            for os in os_types
        ]
        return RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=42,
            scenario_id="basic",
            status=ResourceStatus.READY,
            instances=instances,
            agent_name="Test Agent",
        )

    def test_ctf_participant_only_sees_kali_instances(self):
        """CTF participant sees only the Kali instance, not victims or NGFW."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        range_ctx = self._make_range_with_instances(["kali", "ubuntu", "windows", "panos"])

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_ctx),
            patch("mission_control.context_processors.is_ctf_participant_only", return_value=True),
        ):
            result = active_range(mock_request)

        assert len(result["active_range"].instances) == 1
        assert result["active_range"].instances[0].os_type == "kali"
        assert len(result["connection_urls"]) == 1

    def test_non_ctf_user_sees_all_instances(self):
        """Non-CTF user sees all instances."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        range_ctx = self._make_range_with_instances(["kali", "ubuntu", "windows", "panos"])

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_ctx),
            patch("mission_control.context_processors.is_ctf_participant_only", return_value=False),
        ):
            result = active_range(mock_request)

        assert len(result["active_range"].instances) == 4
        assert len(result["connection_urls"]) == 4

    def test_ctf_participant_no_kali_gets_empty(self):
        """CTF participant with no Kali instance gets empty lists."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        range_ctx = self._make_range_with_instances(["ubuntu", "windows"])

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_ctx),
            patch("mission_control.context_processors.is_ctf_participant_only", return_value=True),
        ):
            result = active_range(mock_request)

        assert len(result["active_range"].instances) == 0
        assert len(result["connection_urls"]) == 0

    def test_ctf_participant_multiple_kali_sees_all_kali(self):
        """CTF participant with multiple Kali instances sees all of them."""
        from mission_control.context_processors import active_range

        mock_request = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.id = 42

        range_ctx = self._make_range_with_instances(["kali", "kali", "windows"])

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_ctx),
            patch("mission_control.context_processors.is_ctf_participant_only", return_value=True),
        ):
            result = active_range(mock_request)

        assert len(result["active_range"].instances) == 2
        assert all(inst.os_type == "kali" for inst in result["active_range"].instances)
        assert len(result["connection_urls"]) == 2
