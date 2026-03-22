"""Tests for agent upload and delete views."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from mission_control.views import agents, delete_agent


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.pk = 1
    user.email = "test@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


def _make_agent(**overrides):
    """Build a mock agent object."""
    defaults = {
        "id": 1,
        "name": "Test Agent",
        "s3_key": "agents/1/abc123_test.msi",
        "original_filename": "test.msi",
        "file_size_bytes": 1024 * 1024,
        "sha256_hash": "abc123",
        "deleted_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestAgentsView:
    def test_requires_login(self, rf):
        request = rf.get("/mc/agents/")
        request.user = AnonymousUser()

        response = agents(request)
        assert response.status_code == 302

    def test_shows_user_agents(self, rf, mock_user):
        request = rf.get("/mc/agents/")
        request.user = mock_user
        agent = _make_agent()

        with (
            patch("mission_control.views.cms_list_agents", return_value=[agent]),
            patch("mission_control.views.get_allowed_extensions", return_value=[".msi"]),
            patch("mission_control.views.render") as mock_render,
        ):
            mock_render.return_value = HttpResponse("ok")
            agents(request)

            context = mock_render.call_args[0][2]
            assert context["agents"] == [agent]

    def test_hides_deleted_agents(self, rf, mock_user):
        """Agents view only shows what cms_list_agents returns (no deleted)."""
        request = rf.get("/mc/agents/")
        request.user = mock_user

        with (
            patch("mission_control.views.cms_list_agents", return_value=[]),
            patch("mission_control.views.get_allowed_extensions", return_value=[".msi"]),
            patch("mission_control.views.render") as mock_render,
        ):
            mock_render.return_value = HttpResponse("ok")
            agents(request)

            context = mock_render.call_args[0][2]
            assert context["agents"] == []

    def test_shows_empty_state(self, rf, mock_user):
        request = rf.get("/mc/agents/")
        request.user = mock_user

        with (
            patch("mission_control.views.cms_list_agents", return_value=[]),
            patch("mission_control.views.get_allowed_extensions", return_value=[".msi"]),
            patch("mission_control.views.render") as mock_render,
        ):
            mock_render.return_value = HttpResponse("ok")
            agents(request)

            context = mock_render.call_args[0][2]
            assert context["agents"] == []


class TestDeleteAgent:
    def test_requires_login(self, rf):
        request = rf.post("/mc/agents/1/delete/")
        request.user = AnonymousUser()

        response = delete_agent(request, 1)
        assert response.status_code == 302

    def test_requires_post(self, rf, mock_user):
        request = rf.get("/mc/agents/1/delete/")
        request.user = mock_user

        response = delete_agent(request, 1)
        assert response.status_code == 405

    @patch("mission_control.views.cms_delete_agent")
    def test_successful_delete(self, mock_cms_delete, rf, mock_user):
        request = rf.post("/mc/agents/1/delete/")
        request.user = mock_user
        # messages framework needs _messages attribute
        request._messages = MagicMock()

        response = delete_agent(request, 1)

        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")
        mock_cms_delete.assert_called_once_with(mock_user, 1)

    @patch("mission_control.views.cms_delete_agent")
    def test_cannot_delete_other_users_agent(self, mock_cms_delete, rf, mock_user):
        """Deleting another user's agent shows error and redirects."""
        from cms.services import CMSError

        mock_cms_delete.side_effect = CMSError("Agent not found or not owned by user")

        request = rf.post("/mc/agents/1/delete/")
        request.user = mock_user
        request._messages = MagicMock()

        response = delete_agent(request, 1)
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

    @patch("mission_control.views.cms_delete_agent")
    def test_cannot_delete_already_deleted(self, mock_cms_delete, rf, mock_user):
        """Deleting already-deleted agent shows error and redirects."""
        from cms.services import CMSError

        mock_cms_delete.side_effect = CMSError("Agent already deleted")

        request = rf.post("/mc/agents/1/delete/")
        request.user = mock_user
        request._messages = MagicMock()

        response = delete_agent(request, 1)
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

    @patch("mission_control.views.cms_delete_agent")
    def test_s3_error_prevents_delete(self, mock_cms_delete, rf, mock_user):
        """S3 error during delete shows error and redirects."""
        from cms.assets.services import AssetError

        mock_cms_delete.side_effect = AssetError("Failed to delete from S3")

        request = rf.post("/mc/agents/1/delete/")
        request.user = mock_user
        request._messages = MagicMock()

        response = delete_agent(request, 1)
        assert response.status_code == 302

    @patch("mission_control.views.cms_delete_agent")
    def test_delete_nonexistent_agent(self, mock_cms_delete, rf, mock_user):
        """Deleting non-existent agent shows error and redirects."""
        from cms.services import CMSError

        mock_cms_delete.side_effect = CMSError("Agent not found")

        request = rf.post("/mc/agents/99999/delete/")
        request.user = mock_user
        request._messages = MagicMock()

        response = delete_agent(request, 99999)
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")
