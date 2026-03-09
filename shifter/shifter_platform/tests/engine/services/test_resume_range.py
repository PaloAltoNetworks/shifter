"""Tests for resume_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus


@pytest.mark.django_db
class TestResumeRange:
    """Tests for resume_range() in engine/services.py.

    Tests the service contract:
    - Inputs: request_id (UUID)
    - Outputs: bool (True if resume initiated or already ready, False otherwise)
    - Side effects: sets status to RESUMING, dispatches Celery resume task
    - Errors: none raised (returns False for not found/invalid state)
    - Logging: DEBUG on entry, INFO on status change, WARNING for not found/invalid state
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_resumable_range(self):
        """Service returns True when range exists and can be resumed."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range"),
        ):
            result = resume_range(request_id)
            assert result is True

    def test_returns_true_when_already_ready(self):
        """Service returns True (idempotent) when range is already ready."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = resume_range(request_id)
            assert result is True

    def test_returns_true_when_already_resuming(self):
        """Service returns True (idempotent) when range is already resuming."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.RESUMING.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = resume_range(request_id)
            assert result is True

    def test_returns_false_when_range_not_found(self):
        """Service returns False when no range found for request_id."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))):
            result = resume_range(request_id)
            assert result is False

    def test_returns_false_when_not_in_paused_state(self):
        """Service returns False when range is not in PAUSED state."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PROVISIONING.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = resume_range(request_id)
            assert result is False

    def test_returns_false_when_destroyed(self):
        """Service returns False when range is destroyed."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYED.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = resume_range(request_id)
            assert result is False

    # -------------------------------------------------------------------------
    # Side effects - status update and Celery task dispatch
    # -------------------------------------------------------------------------

    def test_sets_status_to_resuming(self):
        """Service sets range status to RESUMING."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range"),
        ):
            resume_range(request_id)

            assert mock_range.status == ResourceStatus.RESUMING.value
            mock_range.save.assert_called_once()

    def test_dispatches_celery_resume_task(self):
        """Service dispatches resume_range Celery task with request_id."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range") as mock_resume_task,
        ):
            resume_range(request_id)

            mock_resume_task.delay.assert_called_once_with(str(request_id))

    def test_does_not_modify_range_when_already_ready(self):
        """Service does not modify range when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            resume_range(request_id)

            mock_range.save.assert_not_called()

    def test_does_not_dispatch_task_when_already_ready(self):
        """Service does not dispatch Celery task when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range") as mock_resume_task,
        ):
            resume_range(request_id)

            mock_resume_task.delay.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with request_id."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range"),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            resume_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_warning_when_range_not_found(self, caplog):
        """Service logs warning when range not found."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            resume_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_warning_when_invalid_state(self, caplog):
        """Service logs warning when range is in invalid state for resume."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PROVISIONING.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            resume_range(request_id)

        assert str(request_id) in caplog.text

    def test_logs_info_when_celery_task_dispatched(self, caplog):
        """Service logs info when Celery task is dispatched."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.resume_range"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            resume_range(request_id)

        assert "celery" in caplog.text.lower() or str(request_id) in caplog.text
