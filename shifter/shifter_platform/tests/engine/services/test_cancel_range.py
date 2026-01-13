"""Tests for cancel_range() in engine/services.py."""

import logging
from unittest.mock import Mock
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus
from shared.schemas import RangeContext


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range() in engine/services.py.

    Tests the service contract:
    - Inputs: range_ctx (RangeContext, required)
    - Outputs: None (void function)
    - Side effects: TBD (resource cleanup)
    - Errors: TypeError for None/invalid type, ValueError for invalid range_id
    - Logging: DEBUG on entry, INFO on success, ERROR on validation failures
    """

    # -------------------------------------------------------------------------
    # Input validation - range_ctx type
    # -------------------------------------------------------------------------

    def test_raises_type_error_for_none_range_ctx(self):
        """Service raises TypeError when range_ctx is None."""
        from engine.services import cancel_range

        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

    def test_raises_type_error_for_invalid_type(self):
        """Service raises TypeError when range_ctx is not RangeContext."""
        from engine.services import cancel_range

        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range(42)  # int instead of RangeContext

    def test_raises_type_error_for_dict(self):
        """Service raises TypeError when range_ctx is a dict."""
        from engine.services import cancel_range

        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range({"range_id": 42})

    def test_raises_type_error_for_mock_without_spec(self):
        """Service raises TypeError when range_ctx is wrong Mock type."""
        from engine.services import cancel_range

        mock_ctx = Mock()  # No spec=RangeContext
        mock_ctx.range_id = 42

        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range(mock_ctx)

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

    def test_accepts_valid_range_context(self):
        """Service accepts valid RangeContext without error."""
        from engine.services import cancel_range

        range_ctx = RangeContext(
            request_id=uuid4(),
            range_id=100,
            user_id=5,
            scenario_id="ad_attack_lab",
            status=ResourceStatus.DESTROYED,
            instances=[],
            agent_name="Windows XDR Agent",
        )

        # Should not raise
        cancel_range(range_ctx)

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

    def test_logs_error_for_none_range_ctx(self, caplog):
        """Service logs error when range_ctx is None."""
        from engine.services import cancel_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(TypeError),
        ):
            cancel_range(None)

        assert "none" in caplog.text.lower()

    def test_logs_error_for_invalid_type(self, caplog):
        """Service logs error when range_ctx is invalid type."""
        from engine.services import cancel_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(TypeError),
        ):
            cancel_range("not a RangeContext")

        assert "invalid" in caplog.text.lower() or "str" in caplog.text

    def test_pydantic_validation_allows_none_range_id(self):
        """Pydantic validation allows None range_id (new Request pattern)."""
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

    def test_pydantic_validation_prevents_invalid_range_id(self):
        """Pydantic validation prevents invalid range_id from reaching service."""
        from pydantic import ValidationError

        # RangeContext validator rejects negative range_id before service can log
        with pytest.raises(ValidationError):
            RangeContext(
                request_id=uuid4(),
                range_id=-5,
                user_id=1,
                scenario_id="basic",
                status=ResourceStatus.DESTROYED,
                instances=[],
                agent_name="Test Agent",
            )


@pytest.mark.django_db
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

    def test_returns_true_for_pending_range(self):
        """Service returns True when range is pending."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = cancel_range_by_request(request_id)
            assert result is True

    def test_returns_true_for_provisioning_range(self):
        """Service returns True when range is provisioning."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = cancel_range_by_request(request_id)
            assert result is True

    def test_returns_false_for_ready_range(self):
        """Service returns False when range is already ready (not cancellable)."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = cancel_range_by_request(request_id)
            assert result is False

    def test_returns_false_for_missing_request(self):
        """Service returns False when no range for request_id."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

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

    def test_returns_false_for_destroyed_range(self):
        """Service returns False when range is already destroyed."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = cancel_range_by_request(request_id)
            assert result is False

    def test_returns_false_for_destroying_range(self):
        """Service returns False when range is already destroying."""
        from unittest.mock import patch

        from engine.models import Range
        from engine.services import cancel_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = cancel_range_by_request(request_id)
            assert result is False
