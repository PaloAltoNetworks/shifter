"""Tests for destroy_ngfw() in engine/services.py."""

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from engine.models import Instance, Range, Request
from engine.services import EngineError, destroy_ngfw


@pytest.fixture
def mock_request():
    """Create a mock Request."""
    request = Mock(spec=Request)
    request.request_id = uuid4()
    return request


@pytest.fixture
def mock_ngfw_instance():
    """Create a mock NGFW Instance."""
    instance = Mock(spec=Instance)
    instance.id = 1
    instance.role = "ngfw"
    instance.status = "ready"
    return instance


class TestDestroyNGFW:
    """Tests for destroy_ngfw() in engine/services.py.

    Tests the service contract:
    - Inputs: request_id (UUID)
    - Outputs: bool (True if teardown initiated, False if not found)
    - Errors: EngineError if ranges are still attached
    """

    # -------------------------------------------------------------------------
    # Basic success cases
    # -------------------------------------------------------------------------

    def test_returns_true_when_ngfw_found_and_no_attached_ranges(self, mock_request, mock_ngfw_instance):
        """Service returns True when NGFW exists and has no attached ranges."""
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))
        mock_range_filter = Mock(exists=Mock(return_value=False))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter", return_value=mock_range_filter),
            patch("engine.ecs.start_ngfw_teardown", return_value="arn:aws:ecs:task/123"),
        ):
            result = destroy_ngfw(mock_request.request_id)
            assert result is True

    def test_returns_false_when_request_not_found(self):
        """Service returns False when request doesn't exist."""
        request_id = uuid4()

        with patch.object(Request.objects, "get", side_effect=Request.DoesNotExist):
            result = destroy_ngfw(request_id)
            assert result is False

    def test_returns_false_when_ngfw_instance_not_found(self, mock_request):
        """Service returns False when no NGFW instance found for request."""
        mock_instance_filter = Mock(first=Mock(return_value=None))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
        ):
            result = destroy_ngfw(mock_request.request_id)
            assert result is False

    # -------------------------------------------------------------------------
    # Validation: Attached ranges block deletion
    # -------------------------------------------------------------------------

    def test_raises_engine_error_when_ranges_attached(self, mock_request, mock_ngfw_instance):
        """Service raises EngineError when ranges are attached to the NGFW."""
        mock_attached_ranges = Mock()
        mock_attached_ranges.exists.return_value = True
        mock_attached_ranges.count.return_value = 2
        mock_attached_ranges.values_list.return_value.__getitem__ = Mock(return_value=[101, 102])
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter", return_value=mock_attached_ranges),
        ):
            with pytest.raises(EngineError) as exc_info:
                destroy_ngfw(mock_request.request_id)

            error_message = str(exc_info.value)
            assert "Cannot delete NGFW" in error_message
            assert "2 range(s)" in error_message

    def test_error_message_includes_range_ids(self, mock_request, mock_ngfw_instance):
        """Error message includes attached range IDs for user feedback."""
        mock_attached_ranges = Mock()
        mock_attached_ranges.exists.return_value = True
        mock_attached_ranges.count.return_value = 3
        mock_attached_ranges.values_list.return_value.__getitem__ = Mock(return_value=[101, 102, 103])
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter", return_value=mock_attached_ranges),
        ):
            with pytest.raises(EngineError) as exc_info:
                destroy_ngfw(mock_request.request_id)

            error_message = str(exc_info.value)
            assert "101" in error_message or "[101" in error_message

    def test_filters_ranges_by_active_statuses(self, mock_request, mock_ngfw_instance):
        """Service only checks ranges in active statuses (not destroyed/failed)."""
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter") as mock_filter,
            patch("engine.ecs.start_ngfw_teardown", return_value="arn:aws:ecs:task/123"),
        ):
            mock_filter.return_value = Mock(exists=Mock(return_value=False))

            destroy_ngfw(mock_request.request_id)

            # Verify filter was called with active statuses
            call_kwargs = mock_filter.call_args.kwargs
            assert "status__in" in call_kwargs
            statuses = call_kwargs["status__in"]
            assert Range.Status.READY in statuses
            assert Range.Status.PENDING in statuses
            assert Range.Status.PROVISIONING in statuses
            assert Range.Status.PAUSED in statuses
            assert Range.Status.RESUMING in statuses
            # Should NOT include destroyed/failed
            assert Range.Status.DESTROYED not in statuses
            assert Range.Status.FAILED not in statuses

    # -------------------------------------------------------------------------
    # ECS teardown
    # -------------------------------------------------------------------------

    def test_calls_start_ngfw_teardown_with_request_id(self, mock_request, mock_ngfw_instance):
        """Service calls start_ngfw_teardown with the request_id."""
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))
        mock_range_filter = Mock(exists=Mock(return_value=False))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter", return_value=mock_range_filter),
            patch("engine.ecs.start_ngfw_teardown", return_value="arn") as mock_teardown,
        ):
            destroy_ngfw(mock_request.request_id)

            mock_teardown.assert_called_once_with(mock_request.request_id)

    def test_returns_false_when_teardown_returns_none(self, mock_request, mock_ngfw_instance):
        """Service returns False when start_ngfw_teardown returns None."""
        mock_instance_filter = Mock(first=Mock(return_value=mock_ngfw_instance))
        mock_range_filter = Mock(exists=Mock(return_value=False))

        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=mock_instance_filter),
            patch.object(Range.objects, "filter", return_value=mock_range_filter),
            patch("engine.ecs.start_ngfw_teardown", return_value=None),
        ):
            result = destroy_ngfw(mock_request.request_id)
            assert result is False
