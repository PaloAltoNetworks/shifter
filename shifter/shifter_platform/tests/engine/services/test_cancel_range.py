"""Tests for cancel_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus
from shared.schemas import RangeContext


class TestCancelRange:
    """Tests for cancel_range() in engine/services.py.

    Tests the service contract:
    - Inputs: range_ctx (RangeContext, required)
    - Outputs: None (void function)
    - Side effects: TBD (resource cleanup)
    - Errors: TypeError for None/invalid type, ValueError for invalid range_id
    - Logging: DEBUG on entry, INFO on success, ERROR on validation failures
    """

    @pytest.fixture(autouse=True)
    def _mock_range_lookup(self):
        """Mock Range.objects.get — unit tests don't need real DB lookups."""
        with patch("engine.models.Range.objects.get", return_value=Mock()):
            yield

    # -------------------------------------------------------------------------
    # Input validation - range_ctx type
    # -------------------------------------------------------------------------

    def test_validates_range_ctx_type(self):
        """Service raises TypeError for invalid range_ctx types."""
        from engine.services import cancel_range

        # None
        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

        # Invalid types
        invalid_inputs = [42, {"range_id": 42}, Mock()]  # int, dict, unspec'd mock
        for invalid in invalid_inputs:
            with pytest.raises(TypeError, match="must be RangeContext"):
                cancel_range(invalid)

    # -------------------------------------------------------------------------
    # Input validation - range_id value (handled by Pydantic)
    # -------------------------------------------------------------------------

    def test_pydantic_allows_none_range_id(self):
        """RangeContext Pydantic validator allows None range_id (new pattern)."""
        # range_id is now optional for Request-based ranges
        ctx = RangeContext(
            request_id=uuid4(),
            range_id=None,
            user_id=1,
            scenario_id="basic",
            status=ResourceStatus.DESTROYED,
            instances=[],
            agent_name="Test Agent",
        )
        assert ctx.range_id is None

    def test_pydantic_rejects_negative_range_id(self):
        """RangeContext Pydantic validator rejects negative range_id."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid4(),
                range_id=-1,
                user_id=1,
                scenario_id="basic",
                status=ResourceStatus.DESTROYED,
                instances=[],
                agent_name="Test Agent",
            )

    # -------------------------------------------------------------------------
    # Success case - returns None
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self):
        """Service returns None on successful processing."""
        from engine.services import cancel_range

        range_ctx = RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="basic",
            status=ResourceStatus.DESTROYED,
            instances=[],
            agent_name="Test Agent",
        )

        result = cancel_range(range_ctx)
        assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id, user_id, status."""
        from engine.services import cancel_range

        range_ctx = RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=7,
            scenario_id="basic",
            status=ResourceStatus.DESTROYED,
            instances=[],
            agent_name="Test Agent",
        )

        with caplog.at_level(logging.DEBUG, logger="engine.services"):
            cancel_range(range_ctx)

        assert "42" in caplog.text
        assert "7" in caplog.text or "user_id" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO on success
    # -------------------------------------------------------------------------

    def test_logs_info_on_success(self, caplog):
        """Service logs info when processing completes."""
        from engine.services import cancel_range

        range_ctx = RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="basic",
            status=ResourceStatus.DESTROYED,
            instances=[],
            agent_name="Test Agent",
        )

        with caplog.at_level(logging.INFO, logger="engine.services"):
            cancel_range(range_ctx)

        assert "42" in caplog.text
        assert "processed" in caplog.text.lower() or "cancel" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Logging - ERROR on validation failures
    # -------------------------------------------------------------------------

    def test_logs_error_on_validation_failure(self, caplog):
        """Service logs error for invalid range_ctx."""
        from engine.services import cancel_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(TypeError),
        ):
            cancel_range(None)

        assert "none" in caplog.text.lower()


class TestCancelRangeByRequest:
    """Tests for cancel_range_by_request() in engine/services.py.

    Tests the service contract:
    - Input: request_id (UUID)
    - Output: bool (True if cancelled, False if not found or not cancellable)
    - Side effects: sets status to DESTROYING for cancellable ranges
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_cancellable_statuses(self):
        """Service returns True for PENDING and PROVISIONING ranges."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        cancellable_statuses = [Range.Status.PENDING, Range.Status.PROVISIONING]
        for status in cancellable_statuses:
            request_id = uuid4()
            mock_range = Mock(spec=Range, id=42, status=status)

            with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
                result = cancel_range_by_request(request_id)
                assert result is True, f"Expected True for {status}"

    def test_returns_false_for_non_cancellable_cases(self):
        """Service returns False for non-cancellable statuses or missing range."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        # Non-cancellable statuses
        for status in [Range.Status.READY, Range.Status.DESTROYED, Range.Status.DESTROYING]:
            request_id = uuid4()
            mock_range = Mock(spec=Range, id=42, status=status)

            with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
                result = cancel_range_by_request(request_id)
                assert result is False, f"Expected False for {status}"

        # Missing range
        request_id = uuid4()
        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))):
            result = cancel_range_by_request(request_id)
            assert result is False

    def test_sets_status_to_destroying(self):
        """Service sets range status to DESTROYING."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            cancel_range_by_request(request_id)

            assert mock_range.status == Range.Status.DESTROYING
            mock_range.save.assert_called_once_with(update_fields=["status"])
