"""Tests for cancel_range() in engine/services.py."""

import logging
from unittest.mock import Mock

import pytest

from shared.enums import RangeStatus
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

    def test_pydantic_rejects_none_range_id(self):
        """RangeContext Pydantic validator rejects None range_id."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RangeContext(
                range_id=None,
                user_id=1,
                scenario_id="basic",
                status=RangeStatus.DESTROYED,
                instances=[],
                agent_name="Test Agent",
            )

    def test_pydantic_rejects_negative_range_id(self):
        """RangeContext Pydantic validator rejects negative range_id."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RangeContext(
                range_id=-1,
                user_id=1,
                scenario_id="basic",
                status=RangeStatus.DESTROYED,
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
            range_id=42,
            user_id=1,
            scenario_id="basic",
            status=RangeStatus.DESTROYED,
            instances=[],
            agent_name="Test Agent",
        )

        result = cancel_range(range_ctx)
        assert result is None

    def test_accepts_valid_range_context(self):
        """Service accepts valid RangeContext without error."""
        from engine.services import cancel_range

        range_ctx = RangeContext(
            range_id=100,
            user_id=5,
            scenario_id="ad_attack_lab",
            status=RangeStatus.DESTROYED,
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
            range_id=42,
            user_id=7,
            scenario_id="basic",
            status=RangeStatus.DESTROYED,
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
            range_id=42,
            user_id=1,
            scenario_id="basic",
            status=RangeStatus.DESTROYED,
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

    def test_pydantic_validation_prevents_none_range_id(self):
        """Pydantic validation prevents None range_id from reaching service."""
        from pydantic import ValidationError

        # RangeContext validator rejects None before service can log
        with pytest.raises(ValidationError):
            RangeContext(
                range_id=None,
                user_id=1,
                scenario_id="basic",
                status=RangeStatus.DESTROYED,
                instances=[],
                agent_name="Test Agent",
            )

    def test_pydantic_validation_prevents_invalid_range_id(self):
        """Pydantic validation prevents invalid range_id from reaching service."""
        from pydantic import ValidationError

        # RangeContext validator rejects negative range_id before service can log
        with pytest.raises(ValidationError):
            RangeContext(
                range_id=-5,
                user_id=1,
                scenario_id="basic",
                status=RangeStatus.DESTROYED,
                instances=[],
                agent_name="Test Agent",
            )
