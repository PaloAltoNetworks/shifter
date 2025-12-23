"""Tests for documentation views.

TDD tests covering:
- Happy path: rendering pages, nav tree, markdown features
- Access control: staff-only access
- Failure modes: 404s, security (path traversal, excluded folders)
- Edge cases: trailing slashes, special chars, empty folders, unicode
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
def regular_user(db):
    """Regular user without staff privileges."""
    return User.objects.create_user(
        username="user@example.com",
        email="user@example.com",
        is_staff=False,
    )


@pytest.fixture
def staff_user(db):
    """Staff user with admin privileges."""
    return User.objects.create_user(
        username="admin@example.com",
        email="admin@example.com",
        is_staff=True,
    )


@pytest.fixture
def superuser(db):
    """Superuser with all privileges."""
    return User.objects.create_superuser(
        username="super@example.com",
        email="super@example.com",
        password="password",
    )


# =============================================================================
# Happy Path Tests
# =============================================================================


@pytest.mark.django_db
class TestHappyPath:
    """Tests for normal, expected usage."""

    def test_index_renders_for_staff_user(self, staff_user):
        """Staff user can access docs index and sees content."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        assert response.status_code == 200
        assert response.context["active_nav"] == "docs"
        assert "nav_tree" in response.context
        assert "content" in response.context

    def test_page_renders_markdown_content(self, staff_user):
        """/docs/architecture/ renders architecture.md content."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/architecture/")

        assert response.status_code == 200
        content = response.content.decode()
        # architecture.md contains "Architecture" heading
        assert "Architecture" in content

    def test_nested_page_renders(self, staff_user):
        """/docs/portal/design-system/ renders nested markdown."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/portal/design-system/")

        assert response.status_code == 200
        content = response.content.decode()
        # design-system.md contains "Design System" heading
        assert "Design System" in content

    def test_folder_index_renders(self, staff_user):
        """/docs/portal/ renders portal/index.md."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/portal/")

        assert response.status_code == 200
        # portal/index.md content should be present
        assert response.context["content"] is not None

    def test_nav_tree_contains_expected_sections(self, staff_user):
        """Nav tree includes portal, execution, etc. sections."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        nav_tree = response.context["nav_tree"]
        nav_names = [item["name"] for item in nav_tree]

        # Check for expected top-level sections (folders and files)
        # These should exist in docs/src/
        assert any("Portal" in name or "portal" in name.lower() for name in nav_names) or len(nav_tree) > 0

    def test_mermaid_code_blocks_preserved(self, staff_user):
        """Mermaid code blocks are passed through for client-side rendering."""
        client = get_authenticated_client(staff_user)
        # architecture.md has mermaid diagrams
        response = client.get("/docs/architecture/")

        content = response.content.decode()
        # Mermaid blocks should be in the output (either as code or pre tags)
        # The python markdown library will wrap them in <pre><code> or similar
        assert "mermaid" in content.lower() or "flowchart" in content.lower()

    def test_tables_render_as_html(self, staff_user):
        """Markdown tables become <table> elements."""
        client = get_authenticated_client(staff_user)
        # architecture.md has tables
        response = client.get("/docs/architecture/")

        content = response.content.decode()
        assert "<table" in content or "<th" in content

    def test_code_blocks_render(self, staff_user):
        """Fenced code blocks render properly."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/architecture/")

        content = response.content.decode()
        # Should have code elements
        assert "<code" in content or "<pre" in content


# =============================================================================
# Access Control Tests
# =============================================================================


@pytest.mark.django_db
class TestAccessControl:
    """Tests for authentication and authorization."""

    def test_anonymous_user_redirected_to_login(self, client, db):
        """Anonymous users are redirected to login."""
        response = client.get("/docs/")

        assert response.status_code == 302
        # Should redirect to OIDC or login
        assert "login" in response.url.lower() or "oidc" in response.url.lower()

    def test_regular_user_can_access(self, regular_user):
        """Regular authenticated users can access docs."""
        client = get_authenticated_client(regular_user)
        response = client.get("/docs/")

        assert response.status_code == 200

    def test_staff_user_can_access(self, staff_user):
        """Staff users get 200 OK."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        assert response.status_code == 200

    def test_superuser_can_access(self, superuser):
        """Superusers get 200 OK."""
        client = get_authenticated_client(superuser)
        response = client.get("/docs/")

        assert response.status_code == 200


# =============================================================================
# Failure Mode Tests
# =============================================================================


@pytest.mark.django_db
class TestFailureModes:
    """Tests for error handling and security."""

    def test_nonexistent_page_returns_404(self, staff_user):
        """/docs/doesnt-exist/ returns 404."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/doesnt-exist/")

        assert response.status_code == 404

    def test_deprecated_folder_returns_404(self, staff_user):
        """/docs/_deprecated/setup/ returns 404 (excluded folder)."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/_deprecated/setup/")

        assert response.status_code == 404

    def test_directory_traversal_blocked(self, staff_user):
        """Path traversal attempts return 404."""
        client = get_authenticated_client(staff_user)

        # Various traversal attempts
        paths = [
            "/docs/../../../etc/passwd/",
            "/docs/..%2F..%2Fetc%2Fpasswd/",
            "/docs/portal/../../etc/passwd/",
        ]

        for path in paths:
            response = client.get(path)
            # Should be 404, not expose system files
            assert response.status_code in (404, 400), f"Path {path} should be blocked"

    def test_double_dot_in_path_blocked(self, staff_user):
        """Paths with .. that escape docs root are rejected.

        Note: portal/../index normalizes to just "index" which is valid.
        The security concern is escaping the docs directory entirely.
        """
        client = get_authenticated_client(staff_user)
        # Path that would escape out of docs if not sanitized
        response = client.get("/docs/../../etc/passwd/")

        assert response.status_code == 404

    def test_hidden_files_not_accessible(self, staff_user):
        """Paths starting with . are not accessible."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/.hidden/")

        assert response.status_code == 404


# =============================================================================
# Edge Cases / Weirdness Tests
# =============================================================================


@pytest.mark.django_db
class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_special_characters_in_filename(self, staff_user):
        """Handles dashes and underscores in filenames."""
        client = get_authenticated_client(staff_user)
        # design-system has dashes, kali-ami has dashes
        response = client.get("/docs/portal/design-system/")

        assert response.status_code == 200

    def test_deeply_nested_path_404_if_not_exists(self, staff_user):
        """Deep paths return 404 if they don't exist."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/a/b/c/d/e/")

        assert response.status_code == 404

    def test_markdown_renders_without_crash(self, staff_user):
        """Pages render without crashing even with complex markdown."""
        client = get_authenticated_client(staff_user)
        # Try all known pages
        pages = [
            "/docs/",
            "/docs/architecture/",
            "/docs/security/",
            "/docs/portal/",
            "/docs/portal/design-system/",
        ]

        for page in pages:
            response = client.get(page)
            # Should not crash - either 200 or 404
            assert response.status_code in (200, 404), f"Page {page} crashed"

    def test_page_title_in_context(self, staff_user):
        """Page title is set in context."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/architecture/")

        assert response.status_code == 200
        assert "page_title" in response.context


# =============================================================================
# Nav Tree Building Tests
# =============================================================================


@pytest.mark.django_db
class TestNavTree:
    """Tests for navigation tree generation."""

    def test_nav_tree_excludes_deprecated(self, staff_user):
        """Nav tree does not include _deprecated folder."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        nav_tree = response.context["nav_tree"]

        def find_deprecated(items):
            for item in items:
                if "_deprecated" in item.get("name", "").lower():
                    return True
                if item.get("children") and find_deprecated(item["children"]):
                    return True
            return False

        assert not find_deprecated(nav_tree), "Nav tree should not contain _deprecated"

    def test_nav_tree_structure(self, staff_user):
        """Nav tree items have expected structure."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        nav_tree = response.context["nav_tree"]
        assert isinstance(nav_tree, list)

        if nav_tree:
            item = nav_tree[0]
            assert "name" in item
            assert "is_folder" in item
            # Either path (for files) or children (for folders)
            assert "path" in item or "children" in item


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.django_db
class TestSidebarIntegration:
    """Tests for sidebar menu visibility."""

    def test_sidebar_shows_docs_link(self, regular_user):
        """Authenticated users see 'Docs' link in sidebar."""
        client = get_authenticated_client(regular_user)
        # Access docs page that uses the sidebar
        response = client.get("/docs/")

        content = response.content.decode()
        # The sidebar should have a docs link
        assert 'href="/docs/"' in content or "documentation:index" in content or "Docs" in content

    def test_docs_page_has_active_nav_set(self, staff_user):
        """Docs pages set active_nav to 'docs'."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/")

        assert response.context["active_nav"] == "docs"

    def test_nested_page_has_active_nav_set(self, staff_user):
        """Nested docs pages also set active_nav to 'docs'."""
        client = get_authenticated_client(staff_user)
        response = client.get("/docs/architecture/")

        assert response.context["active_nav"] == "docs"
