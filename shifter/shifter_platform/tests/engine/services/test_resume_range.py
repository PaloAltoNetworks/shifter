"""Tests for resume_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

from shared.enums import ResourceStatus


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

    def test_returns_true_when_ecs_task_started(self):
        """Service returns True when range exists, can be resumed, and ECS task starts."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=task_arn),
        ):
            result = resume_range(request_id)
            assert result is True

    def test_returns_false_when_ecs_returns_none(self):
        """Service returns False when ECS task fails to start (returns None)."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=None),
        ):
            result = resume_range(request_id)
            assert result is False

    def test_returns_true_when_already_ready(self):
        """Service returns True (idempotent) when range is already ready."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
            result = resume_range(request_id)
            assert result is True

    def test_returns_true_when_already_resuming(self):
        """Service returns True (idempotent) when range is already resuming."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.RESUMING.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
            result = resume_range(request_id)
            assert result is True

    def test_returns_false_when_range_not_found(self):
        """Service returns False when no range found for request_id."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
            result = resume_range(request_id)
            assert result is False

    def test_returns_false_when_not_in_paused_state(self):
        """Service returns False when range is not in PAUSED state."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PROVISIONING.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
            result = resume_range(request_id)
            assert result is False

    def test_returns_false_when_destroyed(self):
        """Service returns False when range is destroyed."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYED.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
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
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=task_arn),
        ):
            resume_range(request_id)

            # After the atomic block sets RESUMING and ECS succeeds, status stays RESUMING
            assert mock_range.status == ResourceStatus.RESUMING.value
            mock_range.save.assert_called()

    def test_calls_start_range_operation_with_resume(self):
        """Service calls start_range_operation with 'resume' operation."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=task_arn) as mock_operation,
        ):
            resume_range(request_id)

            mock_operation.assert_called_once_with(request_id, "resume")

    def test_does_not_modify_range_when_already_ready(self):
        """Service does not modify range when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
        ):
            resume_range(request_id)

            mock_range.save.assert_not_called()

    def test_does_not_call_operation_when_already_ready(self):
        """Service does not call start_range_operation when already READY."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.READY.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation") as mock_operation,
        ):
            resume_range(request_id)

            mock_operation.assert_not_called()

    # -------------------------------------------------------------------------
    # ECS failure recovery (Fix 3)
    # -------------------------------------------------------------------------

    def test_reverts_status_when_ecs_returns_none(self):
        """Service reverts status to PAUSED when ECS returns None."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=None),
        ):
            resume_range(request_id)

            assert mock_range.status == ResourceStatus.PAUSED.value

    def test_reverts_status_on_client_error(self):
        """Service reverts status to PAUSED when ECS raises ClientError."""
        from botocore.exceptions import ClientError

        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        error_response = {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}}
        client_error = ClientError(error_response, "RunTask")

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", side_effect=client_error),
        ):
            resume_range(request_id)

            assert mock_range.status == ResourceStatus.PAUSED.value

    def test_returns_false_on_client_error(self):
        """Service returns False when ECS raises ClientError."""
        from botocore.exceptions import ClientError

        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)

        error_response = {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}}
        client_error = ClientError(error_response, "RunTask")

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", side_effect=client_error),
        ):
            result = resume_range(request_id)
            assert result is False

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with request_id."""
        from engine.models import Range
        from engine.services import resume_range

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.PAUSED.value)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=task_arn),
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
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=None)))),
            ),
            patch("django.db.transaction.atomic"),
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
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
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
            patch.object(
                Range.objects,
                "select_for_update",
                return_value=Mock(filter=Mock(return_value=Mock(first=Mock(return_value=mock_range)))),
            ),
            patch("django.db.transaction.atomic"),
            patch("engine.ecs.start_range_operation", return_value=task_arn),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            resume_range(request_id)

        assert task_arn in caplog.text or str(request_id) in caplog.text
