"""Tests for cancel_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range() in engine/services.py.

    Tests the service contract:
    - Inputs: range_id (required int)
    - Outputs: bool (True if cancelled, False otherwise)
    - Side effects: sets status to DESTROYED, sets destroyed_at timestamp
    - Errors: none raised (returns False for invalid states)
    - Logging: DEBUG on entry, INFO on success, WARNING on failure
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_pending_range(self):
        """Service returns True when cancelling a PENDING range."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)
            assert result is True

    def test_returns_true_for_provisioning_range(self):
        """Service returns True when cancelling a PROVISIONING range."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)
            assert result is True

    def test_returns_false_when_range_not_found(self):
        """Service returns False when range doesn't exist."""
        from engine.models import Range
        from engine.services import cancel_range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = cancel_range(999)
            assert result is False

    def test_returns_false_for_ready_range(self):
        """Service returns False when range is READY (not cancellable)."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)
            assert result is False

    def test_returns_false_for_destroyed_range(self):
        """Service returns False when range is already DESTROYED."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)
            assert result is False

    # -------------------------------------------------------------------------
    # Side effects - status and timestamp updates
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroyed(self):
        """Service sets range status to DESTROYED."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)

            assert mock_range.status == Range.Status.DESTROYED

    def test_sets_destroyed_at_timestamp(self):
        """Service sets destroyed_at timestamp."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)

            assert mock_range.destroyed_at is not None

    def test_saves_status_and_destroyed_at(self):
        """Service saves both status and destroyed_at fields."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)

            mock_range.save.assert_called_once_with(update_fields=["status", "destroyed_at"])

    def test_does_not_modify_range_when_not_cancellable(self):
        """Service does not modify range when status is not cancellable."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)

            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Non-cancellable statuses
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "status",
        [
            "READY",
            "PAUSED",
            "RESUMING",
            "DESTROYING",
            "DESTROYED",
            "FAILED",
        ],
    )
    def test_returns_false_for_non_cancellable_status(self, status):
        """Service returns False for ranges not in PENDING or PROVISIONING."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=getattr(Range.Status, status))

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)

            assert result is False
            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            cancel_range(42)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO on success
    # -------------------------------------------------------------------------

    def test_logs_info_when_cancelled(self, caplog):
        """Service logs info when range is cancelled."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            cancel_range(42)

        assert "cancelled" in caplog.text.lower() or "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - WARNING on failure
    # -------------------------------------------------------------------------

    def test_logs_warning_when_range_not_found(self, caplog):
        """Service logs warning when range not found."""
        from engine.models import Range
        from engine.services import cancel_range

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            cancel_range(999)

        assert "not found" in caplog.text.lower() or "999" in caplog.text

    def test_logs_warning_when_not_cancellable(self, caplog):
        """Service logs warning when range is not cancellable."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            cancel_range(42)

        assert "not cancellable" in caplog.text.lower() or "42" in caplog.text
