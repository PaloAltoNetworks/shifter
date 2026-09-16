"""Behavior tests for the mission_control.guacamole_session application service.

Drives the real ``launch_guacamole_session`` use case (issue #991) → real
``engine.services`` (against real READY ``Range`` / NGFW rows) → real
``mission_control.guacamole`` URL builders, for each closed access kind. Only
the genuine external transport boundaries are faked: the boto3 Secrets Manager
client (``secrets_boundary``) and the urllib Guacamole token POST
(``guac_exchange``). No first-party function (the service, its resolvers, the
Engine facade, or the Guacamole broker) is patched — the whole point of the
refactor is that the success path is exercisable this way.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from mission_control.guacamole_bootstrap import BootstrapFailure, BootstrapQueueFull, consume_ready_url
from mission_control.guacamole_session import launch_guacamole_session
from mission_control.models import GuacamoleBootstrapRequest

# transaction=True: the inline bootstrap path calls close_old_connections(),
# which corrupts pytest-django's rolled-back wrapping transaction on PostgreSQL
# (#1524); the guacamole endpoint suites use the same marker.
pytestmark = pytest.mark.django_db(transaction=True)

_PROTOCOL = GuacamoleBootstrapRequest.Protocol


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="guac-svc@example.com", email="guac-svc@example.com")


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    # Run the bootstrap synchronously so a test can assert the persisted outcome.
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


@pytest.fixture
def guac_configured(settings):
    settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"  # nosec B105
    settings.GUACAMOLE_BASE_URL = "https://guac.example.com"
    settings.GUACAMOLE_API_BASE_URL = "https://guac.example.com"


def _consume(launch, user):
    return consume_ready_url(request_id=launch.bootstrap_id, user_id=user.pk)


class TestLaunchSucceeds:
    def test_rdp_resolves_and_mints_a_session_url(
        self, user, guac_configured, range_rdp_instance, secrets_boundary, guac_exchange
    ):
        _rng, instance = range_rdp_instance(user, os_type="kali")

        with secrets_boundary(), guac_exchange():
            launch = launch_guacamole_session(user=user, protocol=_PROTOCOL.RDP, target_id=instance["uuid"])

        assert launch.status == GuacamoleBootstrapRequest.Status.SUCCEEDED
        assert _consume(launch, user).startswith("https://guac.example.com/#/client/")

    def test_range_ssh_resolves_and_mints_a_session_url(
        self, user, guac_configured, range_ssh_instance, secrets_boundary, guac_exchange
    ):
        _rng, instance = range_ssh_instance(user)

        with secrets_boundary(), guac_exchange():
            launch = launch_guacamole_session(user=user, protocol=_PROTOCOL.RANGE_SSH, target_id=instance["uuid"])

        assert launch.status == GuacamoleBootstrapRequest.Status.SUCCEEDED
        assert _consume(launch, user).startswith("https://guac.example.com/#/client/")

    def test_ngfw_ssh_resolves_and_mints_a_session_url(
        self, user, guac_configured, make_ngfw, secrets_boundary, guac_exchange
    ):
        ngfw = make_ngfw(user)

        with secrets_boundary(), guac_exchange():
            launch = launch_guacamole_session(user=user, protocol=_PROTOCOL.NGFW_SSH, target_id=str(ngfw.uuid))

        assert launch.status == GuacamoleBootstrapRequest.Status.SUCCEEDED
        assert _consume(launch, user).startswith("https://guac.example.com/#/client/")


class _FakeGuacClient:
    """A fake ``GuacamoleClient`` capturing the SSH request DTO it is handed."""

    def __init__(self) -> None:
        self.ssh_requests: list[object] = []

    def create_rdp_url(self, req):  # pragma: no cover - SSH path only here
        raise AssertionError("RDP not expected")

    def create_ssh_url(self, req) -> str:
        self.ssh_requests.append(req)
        return "https://fake/#/client/xyz?token=faketoken"


class TestLaunchWithInjectedClient:
    def test_injected_client_substitutes_at_the_service_edge(self, user, range_ssh_instance, secrets_boundary):
        """A fake client mints the URL; no settings binding or urllib is reached.

        The real Engine resolution still runs (real READY range, real SSH-key
        fetch over the boto3 boundary), so the injection does not bypass runtime
        authorization — only the Guacamole transport is faked (issue #993).
        """
        _rng, instance = range_ssh_instance(user)
        fake = _FakeGuacClient()

        with secrets_boundary():
            launch = launch_guacamole_session(
                user=user,
                protocol=_PROTOCOL.RANGE_SSH,
                target_id=instance["uuid"],
                guacamole_client=fake,
            )

        assert launch.status == GuacamoleBootstrapRequest.Status.SUCCEEDED
        assert _consume(launch, user) == "https://fake/#/client/xyz?token=faketoken"
        # The DTO carries the facts the real engine resolution produced.
        req = fake.ssh_requests[0]
        assert req.hostname == "10.50.1.10"
        assert req.ssh_username == "ubuntu"
        assert req.username == "guac-svc@example.com"


class TestLaunchSynchronousFailures:
    def test_missing_signing_secret_fails_closed_with_503(self, user, settings):
        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        target_id = str(uuid4())

        with pytest.raises(BootstrapFailure) as exc:
            launch_guacamole_session(user=user, protocol=_PROTOCOL.RDP, target_id=target_id)

        assert exc.value.status_code == 503
        assert "not configured" in str(exc.value)

    def test_unsupported_access_kind_is_rejected(self, user, guac_configured):
        # The closed dispatch never enqueues an unknown access kind.
        target_id = str(uuid4())

        with pytest.raises(ValueError, match="Unsupported Guacamole access kind"):
            launch_guacamole_session(user=user, protocol="vnc", target_id=target_id)


class TestLaunchSaturation:
    def test_queue_full_emits_saturation_warning_and_propagates(self, user, guac_configured, settings, caplog):
        """A saturated bootstrap pool logs the operational signal and re-raises.

        The adapter maps BootstrapQueueFull to a 503; the service must still emit
        the sanitized worker-capacity warning (its only application-level
        saturation signal) before the exception propagates.
        """
        from mission_control import guacamole_bootstrap

        settings.GUACAMOLE_BOOTSTRAP_WORKERS = 1
        target_id = str(uuid4())
        slots = guacamole_bootstrap._get_slots()
        acquired = slots.acquire(blocking=False)
        try:
            with (
                caplog.at_level(logging.WARNING, logger="mission_control.guacamole_session"),
                pytest.raises(BootstrapQueueFull),
            ):
                launch_guacamole_session(user=user, protocol=_PROTOCOL.RANGE_SSH, target_id=target_id)
        finally:
            if acquired:
                slots.release()

        assert any("worker capacity exhausted" in record.getMessage() for record in caplog.records)


class TestLaunchPersistsWorkerFailure:
    def test_missing_range_is_persisted_as_a_polled_400(self, user, guac_configured):
        # No active range: the worker-side Engine resolution raises ValueError,
        # which the bootstrap records as a FAILED row with a 400 status for the
        # status endpoint to surface (never raised to the launch caller).
        launch = launch_guacamole_session(user=user, protocol=_PROTOCOL.RANGE_SSH, target_id=str(uuid4()))

        assert launch.status == GuacamoleBootstrapRequest.Status.FAILED
        bootstrap = GuacamoleBootstrapRequest.objects.get(pk=launch.bootstrap_id)
        assert bootstrap.error_status_code == 400
