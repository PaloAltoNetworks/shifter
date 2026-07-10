"""Tests for documentation views.

Tests the view logic, not specific documentation content.
Content-specific tests are brittle and break when docs are reorganized.
"""

from unittest.mock import MagicMock

import pytest
from django.http import Http404
from django.test import RequestFactory

from documentation.views import doc_index, doc_page

DOCS_INDEX_URL = "/docs/"


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

    def test_authenticated_user_can_access(self, authenticated_client):
        """Authenticated users get 200 OK from the real rendered docs index."""
        client, _user = authenticated_client()
        response = client.get(DOCS_INDEX_URL)

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

    def test_doc_file_map_keys_slugs_to_trusted_files(self, tmp_path):
        """The doc map keys slugs to real files from a trusted walk; excluded and
        hidden entries are skipped and an index.md is reachable by its folder
        slug. A request path is only ever a key, so no user value reaches a
        filesystem path (CodeQL py/path-injection). Exercises the helper
        directly (no patching of module topology).
        """
        from documentation.views import _doc_file_map

        (tmp_path / "guide.md").write_text("g", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "index.md").write_text("i", encoding="utf-8")
        (tmp_path / "_deprecated").mkdir()
        (tmp_path / "_deprecated" / "old.md").write_text("o", encoding="utf-8")

        mapping = _doc_file_map(tmp_path)

        assert mapping["guide"] == tmp_path / "guide.md"
        assert mapping["sub/index"] == tmp_path / "sub" / "index.md"
        assert mapping["sub"] == tmp_path / "sub" / "index.md"  # folder landing page
        assert "_deprecated/old" not in mapping  # excluded folder skipped


# =============================================================================
# Basic Functionality
# =============================================================================


class TestBasicFunctionality:
    """Tests for core view behavior."""

    def test_index_returns_nav_tree(self, authenticated_client):
        """Index page includes nav_tree in the real render context."""
        client, _user = authenticated_client()
        response = client.get(DOCS_INDEX_URL)

        assert response.status_code == 200
        assert isinstance(response.context["nav_tree"], list)

    def test_index_sets_active_nav(self, authenticated_client):
        """Docs pages set active_nav to 'docs'."""
        client, _user = authenticated_client()
        response = client.get(DOCS_INDEX_URL)

        assert response.context["active_nav"] == "docs"

    def test_nav_tree_excludes_deprecated(self, authenticated_client):
        """Nav tree does not include the _deprecated folder."""
        client, _user = authenticated_client()
        response = client.get(DOCS_INDEX_URL)
        nav_tree = response.context["nav_tree"]

        def find_deprecated(items):
            for item in items:
                if "_deprecated" in item.get("name", "").lower():
                    return True
                if item.get("children") and find_deprecated(item["children"]):
                    return True
            return False

        assert not find_deprecated(nav_tree)
