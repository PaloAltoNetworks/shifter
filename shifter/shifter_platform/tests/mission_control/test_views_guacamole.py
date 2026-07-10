"""Behavior tests for mission_control.views._guacamole — RDP and range-SSH URLs.

Drives the real views → real ``engine.services`` (against real READY ``Range``
rows with provisioned instances) → real ``mission_control.guacamole`` URL
builders. Only the cloud/network boundaries are mocked: the boto3 Secrets
Manager client (``secrets_boundary``) and the urllib Guacamole token POST
(``guac_exchange``), instead of patching ``engine.services.*`` /
``mission_control.guacamole.*`` / the bootstrap enqueue.

NGFW SSH paths are exercised in ``test_api_ngfw_ssh_url.py``; the bootstrap
status/open polling views and the ``_sftp_root_for_os`` helper are pure (no
first-party patching) and unchanged.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from django.test import RequestFactory
from rest_framework.test import force_authenticate

pytestmark = pytest.mark.django_db

VALID_SECRET = "0123456789abcdef0123456789abcdef"  # nosec B105


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="guac-views@example.com", email="guac-views@example.com")


@pytest.fixture
def mock_user():
    """A no-DB user input for the bootstrap status/open views (no engine calls)."""
    user = MagicMock()
    user.id = 1
    user.email = "u@example.com"
    user.is_authenticated = True
    return user


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


@pytest.fixture
def guac_configured(settings):
    settings.GUACAMOLE_JSON_AUTH_SECRET = VALID_SECRET
    settings.GUACAMOLE_BASE_URL = "https://guac.example.com"
    settings.GUACAMOLE_API_BASE_URL = "https://guac.example.com"


def _post(rf, path, payload, user):
    body = json.dumps(payload) if not isinstance(payload, str) else payload
    req = rf.post(path, data=body, content_type="application/json")
    req.user = user
    req.session = {}
    force_authenticate(req, user=user)
    return req


def _json(response):
    return json.loads(response.content)


def _get_status(rf, user, request_id):
    from mission_control.views import guacamole_bootstrap_status

    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/")
    request.user = user
    force_authenticate(request, user=user)
    return guacamole_bootstrap_status(request, request_id)


def _get_open(rf, user, request_id):
    from mission_control.views import guacamole_bootstrap_open

    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/open/")
    request.user = user
    force_authenticate(request, user=user)
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

    def test_first_poll_delivers_url_then_clears_token(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(
            mock_user,
            status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
            result_url="https://guac/secret-token",
        )

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 200
        assert _json(response)["url"] == "https://guac/secret-token"
        bootstrap.refresh_from_db()
        assert bootstrap.result_url == ""
        assert bootstrap.delivered_at is not None

    def test_repeat_poll_does_not_replay_url(self, rf, mock_user):
        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = self._bootstrap(
            mock_user,
            status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
            result_url="https://guac/secret-token",
        )

        first = _get_status(rf, mock_user, bootstrap.id)
        second = _get_status(rf, mock_user, bootstrap.id)

        assert first.status_code == 200
        assert second.status_code == 410
        assert "url" not in _json(second)

    def test_expired_succeeded_poll_clears_parked_url(self, rf, mock_user):
        from datetime import timedelta

        from django.utils import timezone

        from mission_control.models import GuacamoleBootstrapRequest

        bootstrap = GuacamoleBootstrapRequest.objects.create(
            user_id=mock_user.id,
            protocol=GuacamoleBootstrapRequest.Protocol.RDP,
            target_id="vm-1",
            status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
            result_url="https://guac/secret-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = _get_status(rf, mock_user, bootstrap.id)

        assert response.status_code == 410
        assert "url" not in _json(response)
        bootstrap.refresh_from_db()
        assert bootstrap.result_url == ""

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

        settings.GUACAMOLE_JSON_AUTH_SECRET = VALID_SECRET
        request = _post(rf, "/mc/guac/rdp/", "not json", mock_user)
        response = guacamole_rdp_url(request)
        assert response.status_code == 400

    def test_returns_400_when_instance_uuid_missing(self, rf, mock_user, settings):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = VALID_SECRET
        request = _post(rf, "/mc/guac/rdp/", {}, mock_user)
        response = guacamole_rdp_url(request)
        assert response.status_code == 400

    def test_returns_503_when_secret_not_configured(self, rf, user, settings, range_rdp_instance, secrets_boundary):
        from mission_control.views import guacamole_rdp_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        _rng, instance = range_rdp_instance(user, os_type="windows")
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": instance["uuid"]}, user)
        with secrets_boundary():
            response = guacamole_rdp_url(request)
        assert response.status_code == 503

    def test_returns_400_when_no_active_range(self, rf, user, guac_configured):
        from mission_control.views import guacamole_rdp_url

        # Resolution moved into the worker (#929): no range -> the engine service
        # raises ValueError -> polled FAILED bootstrap with status 400.
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": str(uuid4())}, user)
        response = guacamole_rdp_url(request)
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 400

    def test_returns_bootstrap_status_url_on_success(
        self, rf, user, guac_configured, range_rdp_instance, secrets_boundary, guac_exchange
    ):
        from mission_control.views import guacamole_rdp_url

        _rng, instance = range_rdp_instance(user, os_type="kali")
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": instance["uuid"]}, user)
        with secrets_boundary(), guac_exchange():
            response = guacamole_rdp_url(request)
        assert response.status_code == 202
        data = _json(response)
        assert data["status"] == "succeeded"
        status = _get_status(rf, user, data["request_id"])
        assert status.status_code == 200
        assert _json(status)["url"].startswith("https://guac.example.com/#/client/")

    def test_status_returns_500_when_url_generation_raises(
        self, rf, user, settings, range_rdp_instance, secrets_boundary
    ):
        from mission_control.views import guacamole_rdp_url

        # A non-AES-length signing secret makes the real RDP URL build raise.
        settings.GUACAMOLE_JSON_AUTH_SECRET = "abcd"  # nosec B105
        _rng, instance = range_rdp_instance(user, os_type="ubuntu")
        request = _post(rf, "/mc/guac/rdp/", {"instance_uuid": instance["uuid"]}, user)
        with secrets_boundary():
            response = guacamole_rdp_url(request)
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Failed to generate RDP URL"


class TestSftpRootHelper:
    def test_known_os_returns_path(self):
        from mission_control.views._guacamole_builders import _sftp_root_for_os

        assert _sftp_root_for_os("kali") == "/home/kali"
        assert _sftp_root_for_os("ubuntu") == "/home/ubuntu"
        assert _sftp_root_for_os("windows").startswith("/C:")

    def test_unknown_os_returns_none(self):
        from mission_control.views._guacamole_builders import _sftp_root_for_os

        assert _sftp_root_for_os("unknown") is None

    def test_none_returns_none(self):
        from mission_control.views._guacamole_builders import _sftp_root_for_os

        assert _sftp_root_for_os(None) is None


# ---------------------------------------------------------------------------
# guacamole_ssh_url (range SSH)
# ---------------------------------------------------------------------------


class TestGuacamoleSSHURL:
    def test_returns_400_for_invalid_json(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = VALID_SECRET
        request = _post(rf, "/mc/guac/ssh/", "not json", mock_user)
        response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_400_when_instance_uuid_missing(self, rf, mock_user, settings):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = VALID_SECRET
        request = _post(rf, "/mc/guac/ssh/", {}, mock_user)
        response = guacamole_ssh_url(request)
        assert response.status_code == 400

    def test_returns_400_when_no_active_range(self, rf, user, guac_configured):
        from mission_control.views import guacamole_ssh_url

        # Resolution moved into the worker (#929): no range -> ValueError ->
        # polled FAILED bootstrap with status 400.
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": str(uuid4())}, user)
        response = guacamole_ssh_url(request)
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 400

    def test_returns_500_when_secrets_manager_fails(
        self, rf, user, guac_configured, range_ssh_instance, secrets_boundary, secrets_client_factory
    ):
        from mission_control.views import guacamole_ssh_url

        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)

        failing = secrets_client_factory()
        failing.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Secrets Manager error"}}, "GetSecretValue"
        )
        with secrets_boundary(client=failing):
            response = guacamole_ssh_url(request)
        # Secrets Manager fetch runs in the worker now (#929) -> polled 500.
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 500

    def test_returns_bootstrap_status_url_on_success(
        self, rf, user, guac_configured, range_ssh_instance, secrets_boundary, guac_exchange
    ):
        from mission_control.views import guacamole_ssh_url

        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)
        with secrets_boundary(), guac_exchange():
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        data = _json(response)
        assert data["status"] == "succeeded"
        status = _get_status(rf, user, data["request_id"])
        assert status.status_code == 200
        assert _json(status)["url"].startswith("https://guac.example.com/#/client/")

    @pytest.mark.django_db(transaction=True)
    def test_request_returns_while_secrets_manager_is_stalled(
        self, rf, user, guac_configured, range_ssh_instance, guac_exchange, settings
    ):
        """WS-2 acceptance: a stalled Secrets Manager does not block the request.

        With the bootstrap running asynchronously, the view returns 202 while the
        worker is still blocked inside the Secrets Manager fetch — proving the
        credential resolution is off the request thread (so page renders /
        ``/health`` on the same worker are unaffected).
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_BOOTSTRAP_INLINE = False
        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)

        reached_secrets = threading.Event()
        release = threading.Event()

        def stalled_fetch(**_kwargs):
            reached_secrets.set()
            release.wait(timeout=10)
            return {"SecretString": "TEST-SSH-PRIVATE-KEY-MATERIAL"}

        # Capture the worker Future the bootstrap pool returns so the test can
        # block on its completion deterministically, rather than polling the DB
        # against a fixed wall-clock deadline (the poll flaked when the pool
        # thread was CPU-starved under parallel test load). Patching the stdlib
        # executor's submit is a concurrency-boundary mock, not a first-party seam.
        submitted_futures: list = []
        real_submit = ThreadPoolExecutor.submit

        def _capturing_submit(self, fn, /, *args, **kwargs):
            future = real_submit(self, fn, *args, **kwargs)
            submitted_futures.append(future)
            return future

        client = MagicMock()
        client.get_secret_value.side_effect = stalled_fetch

        try:
            with (
                patch("boto3.client", return_value=client),
                patch.object(ThreadPoolExecutor, "submit", _capturing_submit),
                guac_exchange(),
            ):
                response = guacamole_ssh_url(request)

                # Request returned promptly without waiting on the stalled fetch.
                assert response.status_code == 202
                # The worker independently reached the Secrets Manager boundary
                # and is blocked there — i.e. the fetch is off the request path.
                assert reached_secrets.wait(timeout=10)
                release.set()

                from mission_control.models import GuacamoleBootstrapRequest

                # Deterministic wait: block until the worker actually finishes,
                # then assert the persisted outcome. The timeout is only a
                # deadlock guard, never the success-path timing.
                assert submitted_futures, "expected a bootstrap worker to be submitted"
                for future in submitted_futures:
                    future.result(timeout=30)

                bootstrap = GuacamoleBootstrapRequest.objects.get(pk=_json(response)["request_id"])
                assert bootstrap.status == GuacamoleBootstrapRequest.Status.SUCCEEDED
        finally:
            release.set()

    def test_returns_503_when_bootstrap_workers_are_full(
        self, rf, user, guac_configured, range_ssh_instance, secrets_boundary, settings
    ):
        from mission_control import guacamole_bootstrap
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_BOOTSTRAP_WORKERS = 1
        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)

        # Exhaust the single real worker slot so enqueue raises BootstrapQueueFull.
        slots = guacamole_bootstrap._get_slots()
        acquired = slots.acquire(blocking=False)
        try:
            with secrets_boundary():
                response = guacamole_ssh_url(request)
            assert response.status_code == 503
            assert response["Retry-After"] == "1"
        finally:
            if acquired:
                slots.release()

    def test_status_returns_500_when_url_gen_raises_valueerror(
        self, rf, user, settings, range_ssh_instance, secrets_boundary
    ):
        from mission_control.views import guacamole_ssh_url

        settings.GUACAMOLE_JSON_AUTH_SECRET = "abcd"  # nosec B105
        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)
        with secrets_boundary():
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Failed to generate SSH URL"

    def test_status_returns_500_when_token_exchange_errors_unexpectedly(
        self, rf, user, guac_configured, range_ssh_instance, secrets_boundary
    ):
        from mission_control.views import guacamole_ssh_url

        _rng, instance = range_ssh_instance(user)
        request = _post(rf, "/mc/guac/ssh/", {"instance_uuid": instance["uuid"]}, user)

        # An unexpected (non-HTTP/URL) error from the token POST is not caught by
        # get_guacamole_auth_token, so the view's catch-all maps it to 500.
        def _boom(req, timeout=None):
            raise RuntimeError("boom")

        with secrets_boundary(), patch("urllib.request.urlopen", side_effect=_boom):
            response = guacamole_ssh_url(request)
        assert response.status_code == 202
        status = _get_status(rf, user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Internal server error"
