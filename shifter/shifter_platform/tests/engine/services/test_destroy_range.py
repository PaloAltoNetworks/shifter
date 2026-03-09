"""Tests for destroy_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus
from shared.schemas import RangeContext


def make_range_ctx(range_id: int = 42, user_id: int = 7) -> RangeContext:
    """Create a RangeContext for testing."""
    return RangeContext(
        request_id=uuid4(),
        range_id=range_id,
        user_id=user_id,
        scenario_id="basic",
        agent_name="Test Agent",
        status=ResourceStatus.READY,
        instances=[],
    )


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() in engine/services.py.

    Tests the service contract:
    - Inputs: RangeContext (required, with range_id and user_id)
    - Outputs: bool (True if range exists and destruction initiated/in progress, False otherwise)
    - Side effects: sets status to DESTROYING, dispatches Celery destroy task
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

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
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
    # Side effects - status update and Celery task dispatch
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self):
        """Service sets range status to DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
        ):
            destroy_range(range_ctx)

            assert mock_range.status == ResourceStatus.DESTROYING.value
            mock_range.save.assert_any_call(update_fields=["status"])

    def test_dispatches_celery_destroy_task_with_request_id(self):
        """Service dispatches destroy_range Celery task with request_id from range's request."""
        from engine.models import Range
        from engine.services import destroy_range

        request_id = uuid4()
        mock_request = Mock(request_id=request_id)
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42, user_id=99)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range") as mock_destroy_task,
        ):
            destroy_range(range_ctx)

            mock_destroy_task.delay.assert_called_once_with(str(request_id))

    def test_does_not_modify_range_when_already_destroying(self):
        """Service does not modify range when already DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with patch.object(Range.objects, "get", return_value=mock_range):
            destroy_range(range_ctx)

            mock_range.save.assert_not_called()

    def test_does_not_dispatch_task_when_already_destroying(self):
        """Service does not dispatch Celery task when already DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range") as mock_destroy_task,
        ):
            destroy_range(range_ctx)

            mock_destroy_task.delay.assert_not_called()

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

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=getattr(Range.Status, status), request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
        ):
            result = destroy_range(range_ctx)

            assert result is True
            assert mock_range.status == ResourceStatus.DESTROYING.value

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
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

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "DESTROYING" in caplog.text or "destroying" in caplog.text.lower()

    def test_logs_info_when_celery_task_dispatched(self, caplog):
        """Service logs info when Celery task is dispatched."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_request = Mock(request_id=uuid4())
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY, request=mock_request)
        range_ctx = make_range_ctx(range_id=42)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.tasks.destroy_range"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            destroy_range(range_ctx)

        assert "celery" in caplog.text.lower() or "task" in caplog.text.lower()

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


@pytest.mark.django_db
class TestDestroyRangeByRequest:
    """Tests for destroy_range_by_request() in engine/services.py.

    Tests the service contract:
    - Input: request_id (UUID)
    - Output: bool (True if teardown initiated, False if not found or already destroyed)
    - Side effects: sets status to DESTROYING, dispatches Celery destroy task via request_id
    """

    # -------------------------------------------------------------------------
    # Outputs - returns bool indicating success
    # -------------------------------------------------------------------------

    def test_returns_true_for_valid_request(self):
        """Service returns True when range exists and can be destroyed."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.destroy_range"),
        ):
            result = destroy_range_by_request(request_id)
            assert result is True

    def test_returns_false_for_missing_request(self):
        """Service returns False when no range for request_id."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))):
            result = destroy_range_by_request(request_id)
            assert result is False

    def test_returns_false_for_already_destroyed(self):
        """Service returns False when range is already destroyed."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYED.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = destroy_range_by_request(request_id)
            assert result is False

    def test_returns_true_idempotent_for_destroying(self):
        """Service returns True (idempotent) when already destroying."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYING.value)

        with patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))):
            result = destroy_range_by_request(request_id)
            assert result is True

    def test_dispatches_celery_destroy_task_with_request_id(self):
        """Service dispatches destroy_range Celery task with request_id."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.destroy_range") as mock_destroy_task,
        ):
            destroy_range_by_request(request_id)
            mock_destroy_task.delay.assert_called_once_with(str(request_id))

    def test_sets_status_to_destroying(self):
        """Service sets range status to DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range_by_request

        request_id = uuid4()
        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=mock_range))),
            patch("engine.tasks.destroy_range"),
        ):
            destroy_range_by_request(request_id)

            assert mock_range.status == ResourceStatus.DESTROYING.value
            mock_range.save.assert_any_call(update_fields=["status"])
