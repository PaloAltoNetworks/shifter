"""Tests for documentation views.

Tests the view logic, not specific documentation content.
Content-specific tests are brittle and break when docs are reorganized.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.http import Http404, HttpResponse
from django.test import RequestFactory

from documentation.views import doc_index, doc_page


@pytest.fixture
def rf():
    """Django RequestFactory."""
    return RequestFactory()


@pytest.fixture
def mock_user():
    """Authenticated mock user (no DB)."""
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.pk = 1
    return user


@pytest.fixture
def anon_user():
    """Anonymous mock user (no DB)."""
    user = MagicMock()
    user.is_authenticated = False
    user.is_active = False
    user.pk = None
    return user


def _make_request(rf, user, path="/docs/"):
    """Build a GET request with user attached."""
    request = rf.get(path)
    request.user = user
    return request


# =============================================================================
# Access Control
# =============================================================================


class TestAccessControl:
    """Tests for authentication."""

    def test_anonymous_user_redirected_to_login(self, rf, anon_user):
        """Anonymous users are redirected to login."""
        request = _make_request(rf, anon_user)
        response = doc_index(request)

        assert response.status_code == 302
        assert "login" in response.url.lower() or "oidc" in response.url.lower()

    @patch("documentation.views.render")
    def test_authenticated_user_can_access(self, mock_render, rf, mock_user):
        """Authenticated users get 200 OK."""
        mock_render.return_value = HttpResponse(status=200)
        request = _make_request(rf, mock_user)
        response = doc_index(request)

        assert response.status_code == 200


# =============================================================================
# Security
# =============================================================================


class TestSecurity:
    """Tests for security controls."""

    def test_deprecated_folder_returns_404(self, rf, mock_user):
        """/docs/_deprecated/* returns 404 (excluded folder)."""
        request = _make_request(rf, mock_user, "/docs/_deprecated/anything/")

        with pytest.raises(Http404):
            doc_page(request, path="_deprecated/anything")

    def test_directory_traversal_blocked(self, rf, mock_user):
        """Path traversal attempts return 404."""
        traversal_paths = [
            "../../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "../../etc/passwd",
        ]

        for path_str in traversal_paths:
            request = _make_request(rf, mock_user, f"/docs/{path_str}/")
            with pytest.raises(Http404, match=r"Invalid path|Document not found"):
                doc_page(request, path=path_str)

    def test_nonexistent_page_returns_404(self, rf, mock_user):
        """Missing pages return 404."""
        request = _make_request(rf, mock_user, "/docs/this-does-not-exist/")

        with pytest.raises(Http404):
            doc_page(request, path="this-does-not-exist")


# =============================================================================
# Basic Functionality
# =============================================================================


class TestBasicFunctionality:
    """Tests for core view behavior."""

    @patch("documentation.views.render")
    def test_index_returns_nav_tree(self, mock_render, rf, mock_user):
        """Index page includes nav_tree in context."""
        mock_render.return_value = HttpResponse(status=200)
        request = _make_request(rf, mock_user)
        doc_index(request)

        mock_render.assert_called_once()
        context = mock_render.call_args[0][2]
        assert "nav_tree" in context
        assert isinstance(context["nav_tree"], list)

    @patch("documentation.views.render")
    def test_index_sets_active_nav(self, mock_render, rf, mock_user):
        """Docs pages set active_nav to 'docs'."""
        mock_render.return_value = HttpResponse(status=200)
        request = _make_request(rf, mock_user)
        doc_index(request)

        mock_render.assert_called_once()
        context = mock_render.call_args[0][2]
        assert context["active_nav"] == "docs"

    @patch("documentation.views.render")
    def test_nav_tree_excludes_deprecated(self, mock_render, rf, mock_user):
        """Nav tree does not include _deprecated folder."""
        mock_render.return_value = HttpResponse(status=200)
        request = _make_request(rf, mock_user)
        doc_index(request)

        mock_render.assert_called_once()
        context = mock_render.call_args[0][2]
        nav_tree = context["nav_tree"]

        def find_deprecated(items):
            for item in items:
                if "_deprecated" in item.get("name", "").lower():
                    return True
                if item.get("children") and find_deprecated(item["children"]):
                    return True
            return False

        assert not find_deprecated(nav_tree)
