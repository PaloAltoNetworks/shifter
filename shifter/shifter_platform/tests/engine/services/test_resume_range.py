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
    - Side effects: sets status to RESUMING, triggers ECS operation
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
            patch("engine.ecs.start_range_operation", return_value=None),
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
    # Side effects - status update and ECS operation
    # -------------------------------------------------------------------------

    def test_sets_status_to_resuming(self):
        """Service sets range status to RESUMING."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.ecs.start_range_operation", return_value=None),
        ):
            resume_range(request_id)

            assert mock_range.status == ResourceStatus.RESUMING.value
            mock_range.save.assert_called_once()

    def test_calls_start_range_operation_with_resume(self):
        """Service calls start_range_operation with 'resume' operation."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.ecs.start_range_operation", return_value=None) as mock_operation,
        ):
            resume_range(request_id)

            mock_operation.assert_called_once_with(request_id, "resume")

    def test_does_not_modify_range_when_already_ready(self):
        """Service does not modify range when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            resume_range(request_id)

            mock_range.save.assert_not_called()

    def test_does_not_call_operation_when_already_ready(self):
        """Service does not call start_range_operation when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.ecs.start_range_operation") as mock_operation,
        ):
            resume_range(request_id)

            mock_operation.assert_not_called()

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
            patch("engine.ecs.start_range_operation", return_value=None),
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

    def test_logs_info_when_status_changed(self, caplog):
        """Service logs info when ECS task started."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.ecs.start_range_operation", return_value=task_arn),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            resume_range(request_id)

        assert task_arn in caplog.text or str(request_id) in caplog.text
