"""Tests for ngfw_detail view in mission_control/views.py."""

from unittest.mock import Mock, patch
from uuid import uuid4

from django.http import HttpRequest


class TestNGFWDetailView:
    """Tests for ngfw_detail view.

    Tests the view contract:
    - Inputs: request (with authenticated user), app_id (UUID string)
    - Outputs: rendered detail.html with ngfw and linked_ranges in context
    - Side effects: queries NGFW and linked ranges from database
    - Errors: redirects to list view if NGFW not found
    """

    def test_includes_linked_ranges_in_context(self):
        """View queries and includes linked ranges in template context."""
        from mission_control.views import ngfw_detail

        mock_request = Mock(spec=HttpRequest)
        mock_request.method = "GET"
        mock_user = Mock(id=1)
        mock_request.user = mock_user

        # Mock NGFW context
        app_id = uuid4()
        mock_ngfw = Mock(
            app_id=app_id,
            instance_id=597,
            name="DevNGFW",
            status="ready",
        )

        # Mock linked ranges
        mock_range1 = Mock(id=205, status="ready", user=mock_user)
        mock_range2 = Mock(id=197, status="ready", user=mock_user)
        mock_ranges = [mock_range1, mock_range2]

        with (
            patch("mission_control.views.cms_get_ngfw", return_value=mock_ngfw),
            patch("engine.models.Range") as MockRange,
            patch("mission_control.views.render") as mock_render,
        ):
            # Setup Range.objects.filter() to return our mock ranges
            mock_queryset = Mock()
            mock_queryset.order_by = Mock(return_value=mock_ranges)
            MockRange.objects.filter = Mock(return_value=mock_queryset)

            # Call the view
            ngfw_detail(mock_request, str(app_id))

            # Verify Range was queried with correct filters
            MockRange.objects.filter.assert_called_once_with(
                ngfw_instance_id=597,
                user=mock_user,
                destroyed_at__isnull=True,
            )

            # Verify render was called with linked_ranges in context
            mock_render.assert_called_once()
            render_args = mock_render.call_args
            context = render_args[0][2]  # Third argument to render()

            assert "ngfw" in context
            assert "linked_ranges" in context
            assert context["linked_ranges"] == mock_ranges

    def test_includes_empty_linked_ranges_when_none_exist(self):
        """View includes empty list when no ranges are linked to NGFW."""
        from mission_control.views import ngfw_detail

        mock_request = Mock(spec=HttpRequest)
        mock_request.method = "GET"
        mock_user = Mock(id=1)
        mock_request.user = mock_user

        app_id = uuid4()
        mock_ngfw = Mock(
            app_id=app_id,
            instance_id=597,
            name="DevNGFW",
            status="ready",
        )

        with (
            patch("mission_control.views.cms_get_ngfw", return_value=mock_ngfw),
            patch("engine.models.Range") as MockRange,
            patch("mission_control.views.render") as mock_render,
        ):
            # Setup Range.objects.filter() to return empty list
            mock_queryset = Mock()
            mock_queryset.order_by = Mock(return_value=[])
            MockRange.objects.filter = Mock(return_value=mock_queryset)

            # Call the view
            ngfw_detail(mock_request, str(app_id))

            # Verify render was called with empty linked_ranges
            render_args = mock_render.call_args
            context = render_args[0][2]

            assert "linked_ranges" in context
            assert context["linked_ranges"] == []

    def test_orders_linked_ranges_by_created_at_desc(self):
        """View orders linked ranges by created_at descending (newest first)."""
        from mission_control.views import ngfw_detail

        mock_request = Mock(spec=HttpRequest)
        mock_request.method = "GET"
        mock_user = Mock(id=1)
        mock_request.user = mock_user

        app_id = uuid4()
        mock_ngfw = Mock(app_id=app_id, instance_id=597)

        with (
            patch("mission_control.views.cms_get_ngfw", return_value=mock_ngfw),
            patch("engine.models.Range") as MockRange,
            patch("mission_control.views.render"),
        ):
            mock_queryset = Mock()
            MockRange.objects.filter = Mock(return_value=mock_queryset)

            ngfw_detail(mock_request, str(app_id))

            # Verify order_by was called with "-created_at"
            mock_queryset.order_by.assert_called_once_with("-created_at")
