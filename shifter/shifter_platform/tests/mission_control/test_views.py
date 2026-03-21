"""Tests for page-rendering views (dashboard, settings, help).

All ORM access is mocked — no @pytest.mark.django_db markers.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    """Django RequestFactory."""
    return RequestFactory()


@pytest.fixture
def mock_user():
    """A mock authenticated user (no DB)."""
    user = MagicMock()
    user.pk = 1
    user.id = 1
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = False
    user.username = "test@example.com"
    user.email = "test@example.com"
    return user


def _get_request(rf, path="/", user=None):
    """Build a GET request with session and user attached."""
    request = rf.get(path)
    request.user = user or AnonymousUser()
    request.session = {}
    return request


def _post_request(rf, path="/", user=None):
    """Build a POST request with session and user attached."""
    request = rf.post(path)
    request.user = user or AnonymousUser()
    request.session = {}
    return request


# ---------------------------------------------------------------------------
# Dashboard View Tests
# ---------------------------------------------------------------------------


class TestDashboardView:
    def test_requires_login(self, rf):
        from mission_control.views import dashboard

        request = _get_request(rf)
        response = dashboard(request)
        assert response.status_code == 302
        assert "/oidc/authenticate/" in response.url or "login" in response.url.lower()

    def test_requires_get(self, rf, mock_user):
        from mission_control.views import dashboard

        request = _post_request(rf, user=mock_user)
        response = dashboard(request)
        assert response.status_code == 405

    @patch("mission_control.views.render")
    def test_renders_dashboard(self, mock_render, rf, mock_user):
        from mission_control.views import dashboard

        mock_render.return_value = HttpResponse("ok")
        request = _get_request(rf, user=mock_user)
        dashboard(request)

        mock_render.assert_called_once()
        _request, template, context = mock_render.call_args.args
        assert template == "mission_control/dashboard.html"
        assert context["page_title"] == "Ranges"
        assert context["active_nav"] == "ranges"


# ---------------------------------------------------------------------------
# Settings View Tests
# ---------------------------------------------------------------------------


class TestSettingsView:
    def test_requires_login(self, rf):
        from mission_control.views import settings

        request = _get_request(rf)
        response = settings(request)
        assert response.status_code == 302

    def test_requires_get(self, rf, mock_user):
        from mission_control.views import settings

        request = _post_request(rf, user=mock_user)
        response = settings(request)
        assert response.status_code == 405

    @patch("mission_control.views.render")
    def test_renders_settings(self, mock_render, rf, mock_user):
        from mission_control.views import settings

        mock_render.return_value = HttpResponse("ok")
        request = _get_request(rf, user=mock_user)
        settings(request)

        mock_render.assert_called_once()
        _request, template, context = mock_render.call_args.args
        assert template == "mission_control/settings.html"
        assert context["page_title"] == "Settings"
        assert context["active_nav"] == "settings"


# ---------------------------------------------------------------------------
# Help View Tests
# ---------------------------------------------------------------------------


class TestHelpView:
    def test_requires_login(self, rf):
        from mission_control.views import help_page

        request = _get_request(rf)
        response = help_page(request)
        assert response.status_code == 302

    def test_requires_get(self, rf, mock_user):
        from mission_control.views import help_page

        request = _post_request(rf, user=mock_user)
        response = help_page(request)
        assert response.status_code == 405

    @patch("mission_control.views.render")
    def test_renders_help(self, mock_render, rf, mock_user, settings):
        from mission_control.views import help_page

        settings.SHIFTER_SUPPORT_EMAIL = "support@test.example.com"

        mock_render.return_value = HttpResponse("ok")
        request = _get_request(rf, user=mock_user)
        help_page(request)

        mock_render.assert_called_once()
        _request, template, context = mock_render.call_args.args
        assert template == "mission_control/help.html"
        assert context["page_title"] == "Help"
        assert context["active_nav"] == "help"
        assert context["support_email"] == "support@test.example.com"


# ---------------------------------------------------------------------------
# Helper Function Tests
# ---------------------------------------------------------------------------


class TestGetUserStorageUsed:
    @patch("cms.assets.services.AgentConfig")
    def test_returns_zero_for_no_agents(self, mock_agent_config, mock_user):
        from cms.assets.services import get_storage_used

        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": None}
        mock_agent_config.active_for_user.return_value = mock_qs

        assert get_storage_used(mock_user) == 0

    @patch("cms.assets.services.AgentConfig")
    def test_sums_active_agent_sizes(self, mock_agent_config, mock_user):
        from cms.assets.services import get_storage_used

        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 3000}
        mock_agent_config.active_for_user.return_value = mock_qs

        assert get_storage_used(mock_user) == 3000

    @patch("cms.assets.services.AgentConfig")
    def test_excludes_deleted_agents(self, mock_agent_config, mock_user):
        from cms.assets.services import get_storage_used

        # Simulate that active_for_user already excludes deleted agents
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 1000}
        mock_agent_config.active_for_user.return_value = mock_qs

        assert get_storage_used(mock_user) == 1000


# ---------------------------------------------------------------------------
# Upload Lock Tests
# ---------------------------------------------------------------------------


class TestUploadLock:
    def test_check_upload_in_progress_false_by_default(self):
        from mission_control.upload_session import check_upload_in_progress

        session = {}
        assert check_upload_in_progress(session) is False

    def test_upload_lock_expires(self):
        from mission_control.upload_session import UPLOAD_LOCK_TIMEOUT, check_upload_in_progress

        session = {"upload_lock": {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 10}}
        assert check_upload_in_progress(session) is False


# Note: TestRangeToJson was removed as engine.serialization.range_to_dict no longer exists.
# Ranges are now serialized via RangeContext.model_dump() directly in views.
