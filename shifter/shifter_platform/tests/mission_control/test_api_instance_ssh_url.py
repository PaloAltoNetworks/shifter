"""Tests for guacamole_ssh_url view in mission_control/views.py."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from mission_control.views import guacamole_ssh_url


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


@pytest.fixture
def mock_ssh_info():
    header = "-----BEGIN " + "RSA PRIVATE " + "KEY-----"
    footer = "-----END " + "RSA PRIVATE " + "KEY-----"
    return {
        "host": "10.50.1.10",
        "port": 22,
        "username": "ubuntu",
        "private_key": f"{header}\n{'x' * 64}\n{footer}",
        "connection_name": "target-ubuntu",
        "cloud_provider": "gcp",
    }


INSTANCE_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _post_request(rf, user, payload=None):
    request = rf.post(
        "/mc/api/guacamole/ssh-url/",
        data=json.dumps(payload or {"instance_uuid": INSTANCE_UUID}),
        content_type="application/json",
    )
    request.user = user
    return request


class TestApiInstanceSSHURL:
    def test_returns_guacamole_url_for_ready_instance(self, rf, mock_user, mock_ssh_info, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        settings.GUACAMOLE_BASE_URL = "https://guac.example.com"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.get_ssh_connection_info", return_value=mock_ssh_info),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                return_value="https://guac.example.com/#/client/abc?token=xyz",
            ),
        ):
            response = guacamole_ssh_url(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["url"].startswith("https://guac.example.com")

    def test_calls_service_with_user_and_uuid(self, rf, mock_user, mock_ssh_info, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.get_ssh_connection_info", return_value=mock_ssh_info) as mock_service,
            patch("mission_control.guacamole.create_guacamole_ssh_url", return_value="https://url"),
        ):
            guacamole_ssh_url(request)

        mock_service.assert_called_once_with(mock_user, INSTANCE_UUID)

    def test_passes_connection_details_to_guacamole(self, rf, mock_user, mock_ssh_info, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        settings.GUACAMOLE_BASE_URL = "https://guac.example.com"

        request = _post_request(rf, mock_user)

        with (
            patch("engine.services.get_ssh_connection_info", return_value=mock_ssh_info),
            patch("mission_control.guacamole.create_guacamole_ssh_url", return_value="https://url") as mock_guac,
        ):
            guacamole_ssh_url(request)

        call_kwargs = mock_guac.call_args[1]
        assert call_kwargs["connection_name"] == "target-ubuntu"
        assert call_kwargs["hostname"] == "10.50.1.10"
        assert call_kwargs["port"] == 22
        assert call_kwargs["ssh_username"] == "ubuntu"
        assert "BEGIN " + "RSA PRIVATE " + "KEY" in call_kwargs["ssh_private_key"]

    def test_returns_400_for_invalid_json(self, rf, mock_user):
        request = rf.post(
            "/mc/api/guacamole/ssh-url/",
            data="{not-json",
            content_type="application/json",
        )
        request.user = mock_user

        response = guacamole_ssh_url(request)

        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"

    def test_returns_400_when_service_rejects_access(self, rf, mock_user, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        request = _post_request(rf, mock_user)

        with patch("engine.services.get_ssh_connection_info", side_effect=ValueError("Instance not found")):
            response = guacamole_ssh_url(request)

        assert response.status_code == 400
        assert "not found" in json.loads(response.content)["error"].lower()

    def test_returns_503_when_guacamole_not_configured(self, rf, mock_user, mock_ssh_info, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        request = _post_request(rf, mock_user)

        with patch("engine.services.get_ssh_connection_info", return_value=mock_ssh_info):
            response = guacamole_ssh_url(request)

        assert response.status_code == 503
        assert json.loads(response.content)["error"] == "SSH service not configured"
