"""Tests for mission_control.views._guacamole — RDP and range-SSH URL endpoints.

NGFW SSH paths are exercised separately in ``test_api_ngfw_ssh_url.py``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.email = "u@example.com"
    user.is_authenticated = True
    return user


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


def _post(rf, path, payload, user):
    body = json.dumps(payload) if not isinstance(payload, str) else payload
    req = rf.post(path, data=body, content_type="application/json")
    req.user = user
    req.session = {}
    return req


def _json(response):
    return json.loads(response.content)


def _get_status(rf, user, request_id):
    from mission_control.views import guacamole_bootstrap_status

    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/")
    request.user = user
    return guacamole_bootstrap_status(request, request_id)


def _get_open(rf, user, request_id):
    from mission_control.views import guacamole_bootstrap_open

    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/open/")
    request.user = user
    return guacamole_bootstrap_open(request, request_id)


class TestGuacamoleBootstrapStatus:
    def _bootstrap(self, mock_user, *, status, **overrides):
        from datetime import timedelta

        from django.utils import timezone

        from mission_control.models import GuacamoleBootstrapRequest

        defaults = {
            "user_id": mock_user.id,
            "protocol": GuacamoleBootstrapRequest.Protocol.RDP,
            "target_id": "vm-1",
            "status": status,
            "expires_at": timezone.now() + timedelta(minutes=5),
        }
        defaults.update(overrides)
        return GuacamoleBootstrapRequest.objects.create(**defaults)

    def test_returns_404_for_other_user(self, rf, mock_user):
        from datetime import timedelta

        from django.utils import timezone

        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = GuacamoleBootstrapRequest.objects.create(
            user_id=2,
            protocol=GuacamoleBootstrapRequest.Protocol.RDP,
            target_id="vm-1",
            status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
            result_url="https://guac/x",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 404

    def test_returns_retry_after_for_pending_bootstrap(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(mock_user, status=GuacamoleBootstrapRequest.Status.PENDING)

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 200
        assert response["Retry-After"] == "1"
        assert _json(response)["status"] == GuacamoleBootstrapRequest.Status.PENDING

    def test_returns_saved_error_for_failed_bootstrap(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(
            mock_user,
            status=GuacamoleBootstrapRequest.Status.FAILED,
            error_message="Guacamole unavailable",
            error_status_code=503,
        )

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 503
        assert _json(response)["error"] == "Guacamole unavailable"

    def test_marks_pending_bootstrap_expired(self, rf, mock_user):
        from datetime import timedelta

        from django.utils import timezone

        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = GuacamoleBootstrapRequest.objects.create(
            user_id=mock_user.id,
            protocol=GuacamoleBootstrapRequest.Protocol.RDP,
            target_id="vm-1",
            status=GuacamoleBootstrapRequest.Status.PENDING,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 410
        assert _json(response)["error"] == "Guacamole session request expired"
        bootstrap.refresh_from_db()
        assert bootstrap.status == GuacamoleBootstrapRequest.Status.FAILED

    def test_open_page_contains_status_url_for_owner(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(mock_user, status=GuacamoleBootstrapRequest.Status.PENDING)

        response = _get_open(rf, mock_user, bootstrap.id)

        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert f"api/guacamole/bootstrap/{bootstrap.id}/" in body

    def test_open_page_returns_404_for_other_user(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(mock_user, user_id=2, status=GuacamoleBootstrapRequest.Status.PENDING)

        response = _get_open(rf, mock_user, bootstrap.id)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# guacamole_rdp_url
# ---------------------------------------------------------------------------


class TestGuacamoleRDPURL:
    def test_returns_400_for_invalid_json(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        request = _post(rf, "/mc/guac/rdp/", "not json", mock_user)
        response = guacamole_rdp_url(request)
        assert response.status_code == 400

    def test_returns_400_when_instance_uuid_missing(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        request = _post(rf, "/mc/guac/rdp/", {}, mock_user)
        response = guacamole_rdp_url(request)
        assert response.status_code == 400

    def test_returns_503_when_secret_not_configured(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": str(uuid4())}, mock_user)
        conn_info = {
            "os_type": "windows",
            "connection_name": "vm-1",
            "private_ip": "10.0.0.1",
            "rdp_username": "Admin",
            "rdp_password": "pw",
            "ssh_key": None,
        }
        with patch("engine.services.get_rdp_connection_info", return_value=conn_info):
            response = guacamole_rdp_url(request)
        assert response.status_code == 503

    def test_returns_400_when_engine_raises_valueerror(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": str(uuid4())}, mock_user)
        with patch(
            "engine.services.get_rdp_connection_info",
            side_effect=ValueError("not ready"),
        ):
            response = guacamole_rdp_url(request)
        assert response.status_code == 400

    def test_returns_bootstrap_status_url_on_success(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        settings.GUACAMOLE_BASE_URL = "https://guac.example.com"
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": str(uuid4())}, mock_user)
        conn_info = {
            "os_type": "kali",
            "connection_name": "vm-1",
            "private_ip": "10.0.0.1",
            "rdp_username": "kali",
            "rdp_password": "pw",
            "ssh_key": "key",
        }
        with (
            patch("engine.services.get_rdp_connection_info", return_value=conn_info),
            patch(
                "mission_control.guacamole.create_guacamole_rdp_url",
                return_value="https://guac/abc",
            ),
        ):
            response = guacamole_rdp_url(request)
        assert response.status_code == 202
        data = _json(response)
        assert data["status"] == "succeeded"
        status = _get_status(rf, mock_user, data["request_id"])
        assert status.status_code == 200
        assert _json(status)["url"] == "https://guac/abc"

    def test_status_returns_500_when_url_generation_raises(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": str(uuid4())}, mock_user)
        conn_info = {
            "os_type": "ubuntu",
            "connection_name": "vm-1",
            "private_ip": "10.0.0.1",
            "rdp_username": "u",
            "rdp_password": "p",
            "ssh_key": None,
        }
        with (
            patch("engine.services.get_rdp_connection_info", return_value=conn_info),
            patch(
                "mission_control.guacamole.create_guacamole_rdp_url",
                side_effect=ValueError("bad"),
            ),
        ):
            response = guacamole_rdp_url(request)
        assert response.status_code == 202
        status = _get_status(rf, mock_user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Failed to generate RDP URL"


class TestSftpRootHelper:
    def test_known_os_returns_path(self):
        from mission_control.views._guacamole import _sftp_root_for_os

        assert _sftp_root_for_os("kali") == "/home/kali"
        assert _sftp_root_for_os("ubuntu") == "/home/ubuntu"
        assert _sftp_root_for_os("windows").startswith("/C:")

    def test_unknown_os_returns_none(self):
        from mission_control.views._guacamole import _sftp_root_for_os

        assert _sftp_root_for_os("unknown") is None

    def test_none_returns_none(self):
        from mission_control.views._guacamole import _sftp_root_for_os

        assert _sftp_root_for_os(None) is None


# ---------------------------------------------------------------------------
# guacamole_ssh_url (range SSH)
# ---------------------------------------------------------------------------


class TestGuacamoleSSHURL:
    def _ssh_info(self):
        return {
            "connection_name": "kali-1",
            "host": "10.0.0.2",
            "port": 22,
            "username": "kali",
            "private_key": "PEM",
            "cloud_provider": "aws",
        }

    def test_returns_400_for_invalid_json(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", "not json", mock_user)
        response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_400_when_instance_uuid_missing(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {}, mock_user)
        response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_400_when_engine_raises_valueerror(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with patch(
            "engine.services.get_ssh_connection_info",
            side_effect=ValueError("no ssh"),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_400_when_engine_raises_permission_error(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with patch(
            "engine.services.get_ssh_connection_info",
            side_effect=PermissionError("denied"),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_500_when_engine_raises_unexpected(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with patch(
            "engine.services.get_ssh_connection_info",
            side_effect=RuntimeError("boom"),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 500

    def test_returns_bootstrap_status_url_on_success(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with (
            patch("engine.services.get_ssh_connection_info", return_value=self._ssh_info()),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                return_value="https://guac/x",
            ),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        data = _json(response)
        assert data["status"] == "succeeded"
        status = _get_status(rf, mock_user, data["request_id"])
        assert status.status_code == 200
        assert _json(status)["url"] == "https://guac/x"

    def test_returns_503_when_bootstrap_workers_are_full(self, rf, mock_user, settings):
        from mission_control.guacamole_bootstrap import BootstrapQueueFull
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with (
            patch("engine.services.get_ssh_connection_info", return_value=self._ssh_info()),
            patch(
                "mission_control.views._guacamole_bootstrap.enqueue_guacamole_bootstrap",
                side_effect=BootstrapQueueFull,
            ),
        ):
            response = guacamole_ssh_url(request)

        assert response.status_code == 503
        assert response["Retry-After"] == "1"

    def test_status_returns_500_when_url_gen_raises_valueerror(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with (
            patch("engine.services.get_ssh_connection_info", return_value=self._ssh_info()),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                side_effect=ValueError("bad"),
            ),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        status = _get_status(rf, mock_user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Failed to generate SSH URL"

    def test_status_returns_500_when_url_gen_raises_unexpected(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, mock_user)
        with (
            patch("engine.services.get_ssh_connection_info", return_value=self._ssh_info()),
            patch(
                "mission_control.guacamole.create_guacamole_ssh_url",
                side_effect=RuntimeError("boom"),
            ),
        ):
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        status = _get_status(rf, mock_user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Internal server error"


# ---------------------------------------------------------------------------
# api_ngfw_ssh_url — additional error branches
# ---------------------------------------------------------------------------


class TestApiNGFWSSHURLErrorPaths:
    def test_returns_400_on_permission_error(self, rf, mock_user, settings):
        from mission_control.views import api_ngfw_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/ngfw/x/ssh/", {}, mock_user)
        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=PermissionError("denied"),
        ):
            response = api_ngfw_ssh_url(request, str(uuid4()))
        assert response.status_code == 400

    def test_returns_500_on_unexpected_error(self, rf, mock_user, settings):
        from mission_control.views import api_ngfw_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "x" * 32
        request = _post(rf, "/mc/ngfw/x/ssh/", {}, mock_user)
        with patch(
            "engine.services.connect_ngfw_terminal",
            side_effect=RuntimeError("kaboom"),
        ):
            response = api_ngfw_ssh_url(request, str(uuid4()))
        assert response.status_code == 500
