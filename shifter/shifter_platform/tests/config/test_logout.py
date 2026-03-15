"""Tests for the unified logout view (config/views.py:logout_view).

Verifies that:
- OIDC users are logged out and redirected to Cognito's logout endpoint
- Non-OIDC users (magic-link, dev-login) are logged out with a simple session clear
- Unauthenticated requests redirect to the landing page
- Only POST is accepted
"""

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def client(db):
    """Django test client with database access."""
    return Client()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.mark.django_db
class TestLogoutView:
    """Test the unified logout view."""

    def test_non_oidc_user_gets_session_logout(self, client, user):
        """Non-OIDC user (ModelBackend) should get a simple session logout."""
        client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        response = client.post(reverse("logout"))
        assert response.status_code == 302
        assert response.url == "/"

        # Session should be cleared — user is no longer authenticated
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302  # Redirected to login

    def test_oidc_user_redirects_to_cognito_logout(self, client, user):
        """OIDC user should be logged out and redirected to Cognito logout URL."""
        client.force_login(user, backend="config.oidc.ShifterOIDCBackend")

        # Set the backend session key as Django's login() would
        session = client.session
        session[BACKEND_SESSION_KEY] = "config.oidc.ShifterOIDCBackend"
        session.save()

        response = client.post(reverse("logout"))
        assert response.status_code == 302
        # In dev/test (no OIDC_AUTH_DOMAIN env var), provider_logout_url returns "/"
        assert response.url == "/"

        # Session should be cleared
        response = client.get(reverse("dashboard_router"))
        assert response.status_code == 302  # Redirected to login

    def test_unauthenticated_redirects_to_landing(self, client):
        """Unauthenticated POST should redirect to landing page."""
        response = client.post(reverse("logout"))
        assert response.status_code == 302
        assert response.url == "/"

    def test_get_not_allowed(self, client, user):
        """GET requests should be rejected (405 Method Not Allowed)."""
        client.force_login(user)
        response = client.get(reverse("logout"))
        assert response.status_code == 405
