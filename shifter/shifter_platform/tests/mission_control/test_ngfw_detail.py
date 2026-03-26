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
        mock_user = Mock(id=1, pk=1)
        mock_request.user = mock_user

        # Mock NGFW context
        app_id = uuid4()
        mock_ngfw = Mock(
            app_id=app_id,
            instance_id=597,
            name="DevNGFW",
            status="ready",
        )

        # Mock linked ranges as list of dicts (returned by engine.services.get_ranges_for_ngfw)
        mock_ranges = [
            {"id": 205, "status": "ready"},
            {"id": 197, "status": "ready"},
        ]

        with (
            patch("mission_control.views.cms_get_ngfw", return_value=mock_ngfw),
            patch("engine.services.get_ranges_for_ngfw", return_value=mock_ranges) as mock_get_ranges,
            patch("mission_control.views.render") as mock_render,
        ):
            # Call the view
            ngfw_detail(mock_request, str(app_id))

            # Verify get_ranges_for_ngfw was called with correct args
            mock_get_ranges.assert_called_once_with(
                user_id=1,
                ngfw_instance_id=597,
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
        mock_user = Mock(id=1, pk=1)
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
            patch("engine.services.get_ranges_for_ngfw", return_value=[]),
            patch("mission_control.views.render") as mock_render,
        ):
            # Call the view
            ngfw_detail(mock_request, str(app_id))

            # Verify render was called with empty linked_ranges
            render_args = mock_render.call_args
            context = render_args[0][2]

            assert "linked_ranges" in context
            assert context["linked_ranges"] == []

    def test_orders_linked_ranges_by_created_at_desc(self):
        """View delegates ordering to engine.services.get_ranges_for_ngfw.

        The service function handles ordering internally (by -created_at),
        so the view just passes through the results.
        """
        from mission_control.views import ngfw_detail

        mock_request = Mock(spec=HttpRequest)
        mock_request.method = "GET"
        mock_user = Mock(id=1, pk=1)
        mock_request.user = mock_user

        app_id = uuid4()
        mock_ngfw = Mock(app_id=app_id, instance_id=597)

        # Ranges returned already ordered by service
        mock_ranges = [
            {"id": 300, "status": "ready", "created_at": "2026-03-25T10:00:00Z"},
            {"id": 200, "status": "ready", "created_at": "2026-03-24T10:00:00Z"},
        ]

        with (
            patch("mission_control.views.cms_get_ngfw", return_value=mock_ngfw),
            patch("engine.services.get_ranges_for_ngfw", return_value=mock_ranges) as mock_get_ranges,
            patch("mission_control.views.render") as mock_render,
        ):
            ngfw_detail(mock_request, str(app_id))

            # Verify the service was called
            mock_get_ranges.assert_called_once_with(
                user_id=1,
                ngfw_instance_id=597,
            )

            # Verify linked_ranges passed to template
            render_args = mock_render.call_args
            context = render_args[0][2]
            assert context["linked_ranges"] == mock_ranges
