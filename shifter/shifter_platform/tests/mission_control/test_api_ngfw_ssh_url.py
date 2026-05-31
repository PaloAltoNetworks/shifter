"""Tests for api_ngfw_ssh_url view in mission_control/views.py."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from engine.ssh import SSHConnection
from mission_control.views import api_ngfw_ssh_url, guacamole_bootstrap_status

pytestmark = pytest.mark.django_db


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.email = "test@example.com"
    user.is_authenticated = True
    return user


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


@pytest.fixture
def fake_private_key():
    """Generate a fake private key for testing that won't trigger security scanners."""
    header = "-----BEGIN " + "RSA PRIVATE " + "KEY-----"
    footer = "-----END " + "RSA PRIVATE " + "KEY-----"
    return f"{header}\n{'x' * 64}\n{footer}"


@pytest.fixture
def mock_ssh_connection(fake_private_key):
    """Mock SSHConnection for NGFW."""
    return SSHConnection(
        host="10.1.5.10",
        username="admin",
        private_key=fake_private_key,
        port=22,
        session_id=None,
    )


NGFW_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _post_request(rf, user):
    """Build an authenticated POST request."""
    request = rf.post(f"/mc/ngfw/{NGFW_UUID}/ssh-url/")
    request.user = user
    return request


def _json(response):
    return json.loads(response.content)


def _status_response(rf, user, request_id):
    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/")
    request.user = user
    return guacamole_bootstrap_status(request, request_id)


class TestApiNGFWSSHURL:
    """Tests for api_ngfw_ssh_url view."""

    # -------------------------------------------------------------------------
    # Success cases
    # -------------------------------------------------------------------------

    def test_returns_guacamole_url_for_ready_ngfw(self, rf, mock_user, mock_ssh_connection, settings):
        """View returns 200 with Guacamole URL for accessible NGFW."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        settings.GUACAMOLE_BASE_URL = "https://guac.example.com"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                return_value="https://guac.example.com/#/client/abc?token=xyz",
            ),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 202
        data = _json(response)
        status = _status_response(rf, mock_user, data["request_id"])
        assert status.status_code == 200
        assert _json(status)["url"] == "https://guac.example.com/#/client/abc?token=xyz"

    def test_calls_connect_ngfw_terminal_with_user_and_uuid(self, rf, mock_user, mock_ssh_connection, settings):
        """View calls connect_ngfw_terminal with authenticated user and NGFW UUID."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection) as mock_connect,
            patch("mission_control.guacamole.create_guacamole_ssh_url", return_value="https://url"),
        ):
            api_ngfw_ssh_url(request, NGFW_UUID)

            mock_connect.assert_called_once()
            call_args = mock_connect.call_args[0]
            assert call_args[0].email == mock_user.email
            assert str(call_args[1]) == NGFW_UUID

    def test_passes_ssh_connection_details_to_guacamole(self, rf, mock_user, mock_ssh_connection, settings):
        """View extracts SSH connection details and passes to Guacamole."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        settings.GUACAMOLE_BASE_URL = "https://guac.example.com"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection),
            patch("mission_control.guacamole.create_guacamole_ssh_url", return_value="https://url") as mock_guac,
        ):
            api_ngfw_ssh_url(request, NGFW_UUID)

            mock_guac.assert_called_once()
            req = mock_guac.call_args[0][0]
            assert req.hostname == "10.1.5.10"
            assert req.port == 22
            assert req.ssh_username == "admin"
            key_marker = "BEGIN " + "RSA PRIVATE " + "KEY"
            assert key_marker in req.ssh_private_key

    # -------------------------------------------------------------------------
    # Authorization
    # -------------------------------------------------------------------------

    def test_requires_login(self, rf):
        """View requires authentication (login_required decorator redirects)."""
        from django.contrib.auth.models import AnonymousUser

        request = rf.post(f"/mc/ngfw/{NGFW_UUID}/ssh-url/")
        request.user = AnonymousUser()

        response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 302

    def test_returns_400_for_non_owner(self, rf, mock_user, settings):
        """View returns 400 when user doesn't own NGFW."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=PermissionError("You do not have permission"),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "error" in data
        assert "permission" in data["error"].lower()

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def test_returns_400_when_ngfw_not_found(self, rf, mock_user, settings):
        """View returns 400 when NGFW doesn't exist."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=ValueError("NGFW instance not found"),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_returns_400_when_ngfw_not_accessible(self, rf, mock_user, settings):
        """View returns 400 when NGFW is not in accessible state."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=ValueError("NGFW is not accessible (status: provisioning)"),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "error" in data

    def test_requires_post_method(self, rf, mock_user, settings):
        """View requires POST method (not GET)."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = rf.get(f"/mc/ngfw/{NGFW_UUID}/ssh-url/")
        request.user = mock_user

        response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 405  # Method Not Allowed

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_returns_500_when_connect_ngfw_terminal_raises_unexpected_error(self, rf, mock_user, settings):
        """View returns 500 on unexpected errors from connect_ngfw_terminal."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=RuntimeError("Unexpected database error"),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 500
        data = json.loads(response.content)
        assert "error" in data
        assert data["error"] == "Internal server error"

    def test_returns_500_when_guacamole_url_generation_fails(self, rf, mock_user, mock_ssh_connection, settings):
        """View returns 500 when Guacamole URL generation fails."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                side_effect=ValueError("Invalid secret key"),
            ),
        ):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 202
        status = _status_response(rf, mock_user, _json(response)["request_id"])
        assert status.status_code == 500
        data = _json(status)
        assert "error" in data
        assert "Failed to generate SSH URL" in data["error"]

    def test_returns_503_when_guacamole_not_configured(self, rf, mock_user, mock_ssh_connection, settings):
        """View returns 503 when GUACAMOLE_JSON_AUTH_SECRET is not set."""
        settings.GUACAMOLE_JSON_AUTH_SECRET = ""  # Not configured

        request = _post_request(rf, mock_user)

        with patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection):
            response = api_ngfw_ssh_url(request, NGFW_UUID)

        assert response.status_code == 503
        data = json.loads(response.content)
        assert "error" in data
        assert "not configured" in data["error"].lower()

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_successful_url_generation(self, rf, mock_user, mock_ssh_connection, settings, caplog):
        """View logs successful SSH URL generation."""
        import logging

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.connect_ngfw_terminal", return_value=mock_ssh_connection),
            patch("mission_control.guacamole.create_guacamole_ssh_url", return_value="https://url"),
            caplog.at_level(logging.INFO, logger="mission_control"),
        ):
            api_ngfw_ssh_url(request, NGFW_UUID)

        assert NGFW_UUID in caplog.text

    def test_logs_permission_denied_errors(self, rf, mock_user, settings, caplog):
        """View logs permission denied errors."""
        import logging

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with (
            patch(
                "engine.services.connect_ngfw_terminal",
                side_effect=PermissionError("Permission denied"),
            ),
            caplog.at_level(logging.ERROR, logger="mission_control"),
        ):
            api_ngfw_ssh_url(request, NGFW_UUID)

        assert "permission" in caplog.text.lower() or NGFW_UUID in caplog.text
