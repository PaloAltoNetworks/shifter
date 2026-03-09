"""Tests for pause_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus


@pytest.mark.django_db
class TestPauseRange:
    """Tests for pause_range() in engine/services.py.

    Tests the service contract:
    - Inputs: request_id (UUID)
    - Outputs: bool (True if pause initiated or already paused, False otherwise)
    - Side effects: sets status to PAUSING, dispatches Celery pause task
    - Errors: none raised (returns False for not found/invalid state)
    - Logging: DEBUG on entry, INFO on status change, WARNING for not found/invalid state
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_pausable_range(self):
        """Service returns True when range exists and can be paused."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range"),
        ):
            result = pause_range(request_id)
            assert result is True

    def test_returns_true_when_already_paused(self):
        """Service returns True (idempotent) when range is already paused."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = pause_range(request_id)
            assert result is True

    def test_returns_true_when_already_pausing(self):
        """Service returns True (idempotent) when range is already pausing."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSING.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = pause_range(request_id)
            assert result is True

    def test_returns_false_when_range_not_found(self):
        """Service returns False when no range found for request_id."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))):
            result = pause_range(request_id)
            assert result is False

    def test_returns_false_when_not_in_ready_state(self):
        """Service returns False when range is not in READY state."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PROVISIONING.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = pause_range(request_id)
            assert result is False

    # -------------------------------------------------------------------------
    # Side effects - status update and Celery task dispatch
    # -------------------------------------------------------------------------

    def test_sets_status_to_pausing(self):
        """Service sets range status to PAUSING."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range"),
        ):
            pause_range(request_id)

            assert mock_range.status == ResourceStatus.PAUSING.value
            mock_range.save.assert_called_once()

    def test_dispatches_celery_pause_task(self):
        """Service dispatches pause_range Celery task with request_id."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range") as mock_pause_task,
        ):
            pause_range(request_id)

            mock_pause_task.delay.assert_called_once_with(str(request_id))

    def test_does_not_modify_range_when_already_paused(self):
        """Service does not modify range when already PAUSED."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            pause_range(request_id)

            mock_range.save.assert_not_called()

    def test_does_not_dispatch_task_when_already_paused(self):
        """Service does not dispatch Celery task when already PAUSED."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range") as mock_pause_task,
        ):
            pause_range(request_id)

            mock_pause_task.delay.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with request_id."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range"),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            pause_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_warning_when_range_not_found(self, caplog):
        """Service logs warning when range not found."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            pause_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_warning_when_invalid_state(self, caplog):
        """Service logs warning when range is in invalid state for pause."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PROVISIONING.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            pause_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_info_when_celery_task_dispatched(self, caplog):
        """Service logs info when Celery task is dispatched."""
        from engine.models import Range
        from engine.services import pause_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.pause_range"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            pause_range(request_id)

        assert "celery" in caplog.text.lower() or str(request_id) in caplog.text
