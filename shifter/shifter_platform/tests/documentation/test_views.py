"""Tests for documentation views.

Tests the view logic, not specific documentation content.
Content-specific tests are brittle and break when docs are reorganized.
"""

import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


def get_authenticated_client(user):
    """Create a client with OIDC session data to avoid SessionRefresh redirects."""
    client = Client()
    client.force_login(user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def user(db):
    """Authenticated user."""
    return User.objects.create_user(
        username="user@example.com",
        email="user@example.com",
    )


# =============================================================================
# Access Control
# =============================================================================


@pytest.mark.django_db
class TestAccessControl:
    """Tests for authentication."""

    def test_anonymous_user_redirected_to_login(self, client, db):
        """Anonymous users are redirected to login."""
        response = client.get("/docs/")

        assert response.status_code == 302
        assert "login" in response.url.lower() or "oidc" in response.url.lower()

    def test_authenticated_user_can_access(self, user):
        """Authenticated users get 200 OK."""
        client = get_authenticated_client(user)
        response = client.get("/docs/")

        assert response.status_code == 200


# =============================================================================
# Security
# =============================================================================


@pytest.mark.django_db
class TestSecurity:
    """Tests for security controls."""

    def test_deprecated_folder_returns_404(self, user):
        """/docs/_deprecated/* returns 404 (excluded folder)."""
        client = get_authenticated_client(user)
        response = client.get("/docs/_deprecated/anything/")

        assert response.status_code == 404

    def test_directory_traversal_blocked(self, user):
        """Path traversal attempts return 404."""
        client = get_authenticated_client(user)

        paths = [
            "/docs/../../../etc/passwd/",
            "/docs/..%2F..%2Fetc%2Fpasswd/",
            "/docs/../../etc/passwd/",
        ]

        for path in paths:
            response = client.get(path)
            assert response.status_code in (404, 400), f"Path {path} should be blocked"

    def test_nonexistent_page_returns_404(self, user):
        """Missing pages return 404."""
        client = get_authenticated_client(user)
        response = client.get("/docs/this-does-not-exist/")

        assert response.status_code == 404


# =============================================================================
# Basic Functionality
# =============================================================================


@pytest.mark.django_db
class TestBasicFunctionality:
    """Tests for core view behavior."""

    def test_index_returns_nav_tree(self, user):
        """Index page includes nav_tree in context."""
        client = get_authenticated_client(user)
        response = client.get("/docs/")

        assert response.status_code == 200
        assert "nav_tree" in response.context
        assert isinstance(response.context["nav_tree"], list)

    def test_index_sets_active_nav(self, user):
        """Docs pages set active_nav to 'docs'."""
        client = get_authenticated_client(user)
        response = client.get("/docs/")

        assert response.context["active_nav"] == "docs"

    def test_nav_tree_excludes_deprecated(self, user):
        """Nav tree does not include _deprecated folder."""
        client = get_authenticated_client(user)
        response = client.get("/docs/")

        nav_tree = response.context["nav_tree"]

        def find_deprecated(items):
            for item in items:
                if "_deprecated" in item.get("name", "").lower():
                    return True
                if item.get("children") and find_deprecated(item["children"]):
                    return True
            return False

        assert not find_deprecated(nav_tree)
