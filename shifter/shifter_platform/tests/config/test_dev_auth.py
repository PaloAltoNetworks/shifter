"""Tests for development authentication bypass (config/dev_auth.py).

These tests verify the security-critical logic that controls access to dev_login/dev_logout.
"""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

User = get_user_model()


def test_environment_setting_default_is_fail_closed():
    """settings.ENVIRONMENT must not default to 'development' (issue #761).

    A 'development' default means any deployment that omits the ENVIRONMENT
    env var silently activates /dev-login/. The safe default is fail-closed
    ('production'), forcing dev environments to opt in explicitly.
    """
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.py"
    source = settings_path.read_text()
    forbidden = 'os.environ.get("ENVIRONMENT", "development")'
    assert forbidden not in source, (
        f"settings.ENVIRONMENT must not default to 'development' (regression of #761). "
        f"Found {forbidden!r} in {settings_path}"
    )


@pytest.fixture
def client(db):
    """Django test client with database access."""
    return Client()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


class TestDevLoginSecurity:
    """Test security checks for dev_login endpoint."""

    @override_settings(DEBUG=True, ENVIRONMENT="production")
    def test_allows_access_when_debug_true(self, client):
        """dev_login should allow access when DEBUG=True (local development)."""
        response = client.get("/dev-login/")
        # Should not get 403 - should render the login form
        assert response.status_code == 200

    @override_settings(
        DEBUG=False,
        ENVIRONMENT="development",
        ALLOWED_HOSTS=["testserver", "shifter.keplerops.com", "localhost"],
    )
    def test_blocks_public_access_even_in_development(self, client):
        """Deployed dev auth must not be reachable from the public ingress host."""
        response = client.get("/dev-login/", HTTP_HOST="shifter.keplerops.com")
        assert response.status_code == 403
        assert b"local or admin access paths" in response.content

    @override_settings(DEBUG=True, ENVIRONMENT="development")
    def test_allows_access_when_both_true(self, client):
        """dev_login should allow access when both DEBUG and ENVIRONMENT are dev."""
        response = client.get("/dev-login/")
        # Should not get 403 - should render the login form
        assert response.status_code == 200

    @override_settings(DEBUG=False, ENVIRONMENT="production")
    def test_blocks_access_in_production(self, client):
        """dev_login MUST block access in production (DEBUG=False, ENVIRONMENT='production')."""
        response = client.get("/dev-login/")
        # CRITICAL: Must return 403 in production
        assert response.status_code == 403
        assert b"Development auth disabled in production" in response.content

    @override_settings(DEBUG=False, ENVIRONMENT="staging")
    def test_blocks_access_in_non_development_environments(self, client):
        """dev_login should block access in non-development environments (e.g., staging)."""
        response = client.get("/dev-login/")
        # Should return 403 for any ENVIRONMENT other than 'development'
        assert response.status_code == 403

    @override_settings(DEBUG=False, ENVIRONMENT="production")
    def test_blocks_access_when_environment_explicitly_production(self, client):
        """dev_login should block access when ENVIRONMENT is explicitly 'production'."""
        response = client.get("/dev-login/")
        # Should return 403 when ENVIRONMENT is production
        assert response.status_code == 403

    @override_settings(
        DEBUG=False,
        ENVIRONMENT="development",
        ALLOWED_HOSTS=["testserver", "shifter.keplerops.com", "localhost"],
    )
    def test_allows_access_over_localhost_in_development(self, client):
        """Deployed dev auth stays available through loopback/admin tunnels."""
        response = client.get("/dev-login/", HTTP_HOST="localhost:8000")
        assert response.status_code == 200


class TestDevLogoutSecurity:
    """Test security checks for dev_logout endpoint."""

    @override_settings(DEBUG=True, ENVIRONMENT="production")
    def test_allows_access_when_debug_true(self, client, user):
        """dev_logout should allow access when DEBUG=True."""
        client.force_login(user)
        response = client.get("/dev-logout/")
        # Should not get 403
        assert response.status_code == 302  # Redirect

    @override_settings(
        DEBUG=False,
        ENVIRONMENT="development",
        ALLOWED_HOSTS=["testserver", "shifter.keplerops.com", "localhost"],
    )
    def test_allows_access_when_environment_development(self, client, user):
        """dev_logout stays available through localhost/admin paths only."""
        client.force_login(user)
        response = client.get("/dev-logout/", HTTP_HOST="localhost:8000")
        assert response.status_code == 302

    @override_settings(
        DEBUG=False,
        ENVIRONMENT="development",
        ALLOWED_HOSTS=["testserver", "shifter.keplerops.com", "localhost"],
    )
    def test_blocks_public_access_in_development(self, client, user):
        client.force_login(user)
        response = client.get("/dev-logout/", HTTP_HOST="shifter.keplerops.com")
        assert response.status_code == 403
        assert b"local or admin access paths" in response.content

    @override_settings(DEBUG=False, ENVIRONMENT="production")
    def test_blocks_access_in_production(self, client, user):
        """dev_logout MUST block access in production."""
        client.force_login(user)
        response = client.get("/dev-logout/")
        # CRITICAL: Must return 403 in production
        assert response.status_code == 403
        assert b"Development auth disabled in production" in response.content


class TestDevLoginFunctionality:
    """Test the actual login functionality when access is allowed."""

    @override_settings(DEBUG=True)
    def test_get_request_renders_form(self, client):
        """GET request should render the dev_login form."""
        response = client.get("/dev-login/")
        assert response.status_code == 200

    @override_settings(DEBUG=True)
    def test_post_creates_user_and_logs_in(self, client, db):
        """POST should create user if not exists and log them in."""
        email = "newuser@example.com"
        response = client.post("/dev-login/", {"email": email})

        # Should create the user
        assert User.objects.filter(username=email).exists()
        user = User.objects.get(username=email)
        assert user.email == email
        assert user.is_active

        # Should redirect to dashboard
        assert response.status_code == 302
        assert response.url == reverse("mission_control:dashboard")

    @override_settings(DEBUG=True)
    def test_post_with_existing_user(self, client, user, db):
        """POST with existing user email should log them in without creating duplicate."""
        initial_user_count = User.objects.count()

        response = client.post("/dev-login/", {"email": user.email})

        # Should not create new user
        assert User.objects.count() == initial_user_count

        # Should redirect to dashboard
        assert response.status_code == 302

    @override_settings(DEBUG=True)
    def test_post_without_email_uses_default(self, client, db):
        """POST without email should use default dev@example.com."""
        response = client.post("/dev-login/", {})

        # Should create user with default email
        assert User.objects.filter(username="dev@example.com").exists()
        assert response.status_code == 302
