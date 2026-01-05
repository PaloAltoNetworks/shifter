"""Tests for destroy_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest

from shared.enums import RangeStatus
from shared.schemas import RangeContext


def make_range_ctx(range_id: int = 42, user_id: int = 7) -> RangeContext:
    """Create a RangeContext for testing."""
    return RangeContext(
        range_id=range_id,
        user_id=user_id,
        scenario_id="basic",
        agent_name="Test Agent",
        status=RangeStatus.READY,
        instances=[],
    )


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() in engine/services.py.

    Tests the service contract:
    - Inputs: RangeContext (required, with range_id and user_id)
    - Outputs: bool (True if range exists and destruction initiated/in progress, False otherwise)
    - Side effects: sets status to DESTROYING, triggers ECS teardown, stores task ARN
    - Errors: none raised (returns False for not found/already destroyed)
    - Logging: DEBUG on entry, INFO on status change, WARNING for not found/already destroyed
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_destroyable_range(self):
        """Service returns True when range exists and can be destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
        ):
            result = destroy_range(range_ctx)
            assert result is True

    def test_returns_true_when_already_destroying(self):
        """Service returns True (idempotent) when range is already being destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = destroy_range(range_ctx)
            assert result is True

    def test_returns_false_when_range_not_found(self):
        """Service returns False when range doesn't exist."""
        from engine.models import Range
        from engine.services import destroy_range

        range_ctx = make_range_ctx(range_id=999)

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = destroy_range(range_ctx)
            assert result is False

    def test_returns_false_when_already_destroyed(self):
        """Service returns False when range is already destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)
        range_ctx = make_range_ctx(range_id=42)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = destroy_range(range_ctx)
            assert result is False

    # -------------------------------------------------------------------------
    # Side effects - status update and ECS teardown
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self):
        """Service sets range status to DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
        ):
            destroy_range(range_ctx)

            assert mock_range.status == RangeStatus.DESTROYING.value
            mock_range.save.assert_any_call(update_fields=["status"])

    def test_calls_start_teardown_with_range_id_and_user_id_from_context(self):
        """Service calls start_teardown with range_id and user_id from RangeContext."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42, user_id=99)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None) as mock_teardown,
        ):
            destroy_range(range_ctx)

            # user_id comes from RangeContext, not range_obj
            mock_teardown.assert_called_once_with(42, 99)

    def test_stores_task_arn_when_returned(self):
        """Service stores ECS task ARN when start_teardown returns one."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=task_arn),
        ):
            destroy_range(range_ctx)

            assert mock_range.step_function_execution_arn == task_arn
            mock_range.save.assert_any_call(update_fields=["step_function_execution_arn"])

    def test_does_not_store_task_arn_when_none(self):
        """Service does not save ARN field when start_teardown returns None."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
        ):
            destroy_range(range_ctx)

            # Should only save status, not ARN
            calls = list(mock_range.save.call_args_list)
            assert len(calls) == 1
            assert calls[0] == ((), {"update_fields": ["status"]})

    def test_does_not_modify_range_when_already_destroying(self):
        """Service does not modify range when already DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with patch.object(Range.objects, "get", return_value=mock_range):
            destroy_range(range_ctx)

            mock_range.save.assert_not_called()

    def test_does_not_call_teardown_when_already_destroying(self):
        """Service does not call start_teardown when already DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown") as mock_teardown,
        ):
            destroy_range(range_ctx)

            mock_teardown.assert_not_called()

    # -------------------------------------------------------------------------
    # All destroyable statuses work
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "status",
        [
            "PENDING",
            "PROVISIONING",
            "READY",
            "PAUSED",
            "RESUMING",
            "FAILED",
        ],
    )
    def test_destroys_range_in_destroyable_status(self, status):
        """Service destroys ranges in any non-terminal, non-destroying status."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=getattr(Range.Status, status))
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
        ):
            result = destroy_range(range_ctx)

            assert result is True
            assert mock_range.status == RangeStatus.DESTROYING.value

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO on status change
    # -------------------------------------------------------------------------

    def test_logs_info_when_status_changed(self, caplog):
        """Service logs info when status is set to DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=None),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "DESTROYING" in caplog.text or "destroying" in caplog.text.lower()

    def test_logs_info_when_ecs_task_started(self, caplog):
        """Service logs info when ECS task is started."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        range_ctx = make_range_ctx(range_id=42)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-id"

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value=task_arn),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert task_arn in caplog.text or "task" in caplog.text.lower()

    def test_logs_info_when_already_destroying(self, caplog):
        """Service logs info when range is already being destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "already destroying" in caplog.text.lower() or "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - WARNING on not found / already destroyed
    # -------------------------------------------------------------------------

    def test_logs_warning_when_range_not_found(self, caplog):
        """Service logs warning when range not found."""
        from engine.models import Range
        from engine.services import destroy_range

        range_ctx = make_range_ctx(range_id=999)

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "not found" in caplog.text.lower() or "999" in caplog.text

    def test_logs_warning_when_already_destroyed(self, caplog):
        """Service logs warning when range is already destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "already destroyed" in caplog.text.lower() or "42" in caplog.text
