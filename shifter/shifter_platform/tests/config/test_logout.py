"""Tests for the unified logout view (config/views.py:logout_view).

Verifies that:
- OIDC users are logged out and redirected to Cognito's logout endpoint
- Non-OIDC users (magic-link, dev-login) are logged out with a simple session clear
- Unauthenticated requests redirect to the landing page
- Only POST is accepted
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY
from django.test import RequestFactory

from config.views import logout_view


@pytest.fixture
def rf():
    """Django RequestFactory."""
    return RequestFactory()


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    user = MagicMock()
    user.is_authenticated = True
    user.email = "test@example.com"
    return user


class TestLogoutView:
    """Test the unified logout view."""

    def test_non_oidc_user_gets_session_logout(self, rf, mock_user):
        """Non-OIDC user (ModelBackend) should get a simple session logout."""
        request = rf.post("/logout/")
        request.user = mock_user
        request.session = {"_auth_user_backend": "django.contrib.auth.backends.ModelBackend"}

        with patch("config.views.logout") as mock_logout:
            response = logout_view(request)

        mock_logout.assert_called_once_with(request)
        assert response.status_code == 302
        assert response.url == "/"

    def test_oidc_user_redirects_to_cognito_logout(self, rf, mock_user):
        """OIDC user should be logged out and redirected to Cognito logout URL."""
        request = rf.post("/logout/")
        request.user = mock_user
        request.session = {
            BACKEND_SESSION_KEY: "config.oidc.ShifterOIDCBackend",
        }

        # No OIDC_OP_LOGOUT_URL_METHOD configured, so falls back to LOGOUT_REDIRECT_URL
        with patch("config.views.logout") as mock_logout:
            response = logout_view(request)

        mock_logout.assert_called_once_with(request)
        assert response.status_code == 302
        # In dev/test (no OIDC_AUTH_DOMAIN env var), provider_logout_url returns "/"
        assert response.url == "/"

    def test_unauthenticated_redirects_to_landing(self, rf):
        """Unauthenticated POST should redirect to landing page."""
        request = rf.post("/logout/")
        anon = MagicMock()
        anon.is_authenticated = False
        request.user = anon

        response = logout_view(request)
        assert response.status_code == 302
        assert response.url == "/"

    def test_get_not_allowed(self, rf, mock_user):
        """GET requests should be rejected (405 Method Not Allowed)."""
        request = rf.get("/logout/")
        request.user = mock_user

        response = logout_view(request)
        assert response.status_code == 405
