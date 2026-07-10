"""Behavior tests for the guacamole_ssh_url view in mission_control/views.

Drives the real view → real ``engine.services.get_ssh_connection_info`` (against
a real READY ``Range`` with a provisioned instance) → real
``mission_control.guacamole.create_guacamole_ssh_url``. Only the cloud/network
boundaries are mocked: the boto3 Secrets Manager client that yields the SSH key
(``secrets_boundary``) and the urllib Guacamole token POST (``guac_exchange``),
instead of patching ``engine.services.get_ssh_connection_info`` /
``mission_control.guacamole.create_guacamole_ssh_url``.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from rest_framework.test import force_authenticate

from mission_control.views import guacamole_bootstrap_status, guacamole_ssh_url

pytestmark = pytest.mark.django_db

User = get_user_model()

INSTANCE_UUID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ssh-url@example.com", email="ssh-url@example.com")


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    # Run the bootstrap inline so the POST builds the URL synchronously.
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


@pytest.fixture
def guac_configured(settings):
    settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"  # nosec B105
    settings.GUACAMOLE_BASE_URL = "https://guac.example.com"
    # GUACAMOLE_API_BASE_URL is derived from GUACAMOLE_BASE_URL at settings-load
    # time, so override it explicitly (it is used for the token-exchange URL).
    settings.GUACAMOLE_API_BASE_URL = "https://guac.example.com"


def _post_request(rf, user, payload=None):
    request = rf.post(
        "/mission-control/api/guacamole/ssh-url/",
        data=json.dumps(payload or {"instance_uuid": INSTANCE_UUID}),
        content_type="application/json",
    )
    request.user = user
    force_authenticate(request, user=user)
    return request


def _json(response):
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    return json.loads(response.content)


def _status_response(rf, user, request_id):
    request = rf.get(f"/mission-control/api/guacamole/bootstrap/{request_id}/")
    request.user = user
    force_authenticate(request, user=user)
    return guacamole_bootstrap_status(request, request_id)


class TestApiInstanceSSHURL:
    def test_returns_guacamole_url_for_ready_instance(
        self, rf, user, guac_configured, range_ssh_instance, secrets_boundary, guac_exchange
    ):
        range_ssh_instance(user)
        request = _post_request(rf, user)

        with secrets_boundary(), guac_exchange():
            response = guacamole_ssh_url(request)

        assert response.status_code == 202
        data = _json(response)
        status = _status_response(rf, user, data["request_id"])
        assert status.status_code == 200
        url = _json(status)["url"]
        assert url.startswith("https://guac.example.com/#/client/")
        assert "token=token123" in url

    def test_passes_connection_details_to_guacamole(
        self,
        rf,
        user,
        guac_configured,
        range_ssh_instance,
        secrets_boundary,
        guac_exchange,
        secret_key_128,
        ssh_key_pem,
    ):
        range_ssh_instance(user)
        request = _post_request(rf, user)

        with secrets_boundary(), guac_exchange() as exchange:
            guacamole_ssh_url(request)

        # The instance details resolved by the real engine service flow into the
        # signed Guacamole payload that was POSTed.
        connections = exchange.posted_payload(secret_key_128)["connections"]
        assert "target-ubuntu" in connections
        params = connections["target-ubuntu"]["parameters"]
        assert params["hostname"] == "10.50.1.10"
        assert params["port"] == "22"
        assert params["username"] == "ubuntu"
        assert params["private-key"] == ssh_key_pem

    def test_returns_400_for_invalid_json(self, rf, user):
        request = rf.post(
            "/mission-control/api/guacamole/ssh-url/",
            data="{not-json",
            content_type="application/json",
        )
        request.user = user
        force_authenticate(request, user=user)

        response = guacamole_ssh_url(request)

        assert response.status_code == 400
        assert _json(response)["error"] == "Invalid JSON"

    def test_returns_400_when_instance_not_in_range(self, rf, user, guac_configured, range_ssh_instance):
        # A READY range exists, but the requested instance uuid is not in it.
        # Resolution moved into the worker (#929) -> polled FAILED bootstrap (400).
        range_ssh_instance(user, uuid="a-different-instance-uuid")
        request = _post_request(rf, user)

        response = guacamole_ssh_url(request)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 400
        assert "not found" in _json(status)["error"].lower()

    def test_returns_503_when_guacamole_not_configured(self, rf, user, settings, range_ssh_instance, secrets_boundary):
        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        range_ssh_instance(user)
        request = _post_request(rf, user)

        with secrets_boundary():
            response = guacamole_ssh_url(request)

        assert response.status_code == 503
        assert _json(response)["error"] == "SSH service not configured"
