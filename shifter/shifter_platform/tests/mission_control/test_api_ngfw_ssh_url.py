"""Behavior tests for the api_ngfw_ssh_url view in mission_control/views.

Drives the real view → real ``engine.services.connect_ngfw_terminal`` (against a
real NGFW ``Instance`` + ``Request``) → real
``mission_control.guacamole.create_guacamole_ssh_url``. Only the cloud/network
boundaries are mocked: the boto3 Secrets Manager client that yields the NGFW SSH
key (``secrets_boundary``) and the urllib Guacamole token POST
(``guac_exchange``), instead of patching ``engine.services.connect_ngfw_terminal``
/ ``mission_control.guacamole.create_guacamole_ssh_url``.

Two generic fault-injection tests are folded into real-boundary equivalents: the
500 path is driven by a real Secrets Manager ``ClientError``, and the URL-build
failure by a real invalid signing secret.
"""

import json
import logging

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from rest_framework.test import force_authenticate

from mission_control.views import api_ngfw_ssh_url, guacamole_bootstrap_status

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ngfw-ssh@example.com", email="ngfw-ssh@example.com")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="ngfw-other@example.com", email="ngfw-other@example.com")


@pytest.fixture(autouse=True)
def guacamole_bootstrap_inline(settings):
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True


@pytest.fixture
def guac_secret(settings):
    settings.GUACAMOLE_JSON_AUTH_SECRET = "0123456789abcdef0123456789abcdef"  # nosec B105


@pytest.fixture
def guac_configured(guac_secret, settings):
    settings.GUACAMOLE_BASE_URL = "https://guac.example.com"
    settings.GUACAMOLE_API_BASE_URL = "https://guac.example.com"


def _post_request(rf, user, app_id):
    request = rf.post(f"/mc/ngfw/{app_id}/ssh-url/")
    request.user = user
    force_authenticate(request, user=user)
    return request


def _json(response):
    return json.loads(response.content)


def _status_response(rf, user, request_id):
    request = rf.get(f"/mc/api/guacamole/bootstrap/{request_id}/")
    request.user = user
    force_authenticate(request, user=user)
    return guacamole_bootstrap_status(request, request_id)


class TestApiNGFWSSHURL:
    # ---- success ----------------------------------------------------------

    def test_returns_guacamole_url_for_ready_ngfw(
        self, rf, user, guac_configured, make_ngfw, secrets_boundary, guac_exchange
    ):
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with secrets_boundary(), guac_exchange():
            response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 200
        url = _json(status)["url"]
        assert url.startswith("https://guac.example.com/#/client/")
        assert "token=token123" in url

    def test_passes_ssh_connection_details_to_guacamole(
        self, rf, user, guac_configured, make_ngfw, secrets_boundary, guac_exchange, secret_key_128, ssh_key_pem
    ):
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with secrets_boundary(), guac_exchange() as exchange:
            api_ngfw_ssh_url(request, app_id)

        connections = exchange.posted_payload(secret_key_128)["connections"]
        params = connections[f"ngfw-{app_id}"]["parameters"]
        assert params["hostname"] == "10.1.5.10"
        assert params["port"] == "22"
        assert params["username"] == "admin"
        assert params["private-key"] == ssh_key_pem

    # ---- authorization ----------------------------------------------------

    def test_requires_login(self, rf):
        from django.contrib.auth.models import AnonymousUser

        request = rf.post("/mc/ngfw/some-uuid/ssh-url/")
        request.user = AnonymousUser()

        response = api_ngfw_ssh_url(request, "some-uuid")

        assert response.status_code == 401

    def test_returns_400_for_non_owner(self, rf, user, other_user, guac_secret, make_ngfw):
        # Ownership resolution moved into the bootstrap worker (#929), so the
        # permission failure surfaces as a polled FAILED bootstrap, not a
        # synchronous 400.
        ngfw = make_ngfw(user, owner=other_user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 400
        assert "permission" in _json(status)["error"].lower()

    # ---- validation -------------------------------------------------------

    def test_returns_400_when_ngfw_not_found(self, rf, user, guac_secret):
        from uuid import uuid4

        app_id = str(uuid4())
        request = _post_request(rf, user, app_id)

        response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 400
        assert "not found" in _json(status)["error"].lower()

    def test_returns_400_when_ngfw_not_accessible(self, rf, user, guac_secret, make_ngfw):
        from shared.enums import ResourceStatus

        ngfw = make_ngfw(user, status=ResourceStatus.PROVISIONING.value)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 400
        assert "error" in _json(status)

    def test_requires_post_method(self, rf, user, guac_secret):
        request = rf.get("/mc/ngfw/some-uuid/ssh-url/")
        request.user = user

        response = api_ngfw_ssh_url(request, "some-uuid")

        assert response.status_code == 405

    # ---- error handling (real boundary faults) ----------------------------

    def test_returns_500_when_secrets_manager_fails(
        self, rf, user, guac_secret, make_ngfw, secrets_boundary, secrets_client_factory
    ):
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        failing = secrets_client_factory()
        failing.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Secrets Manager error"}}, "GetSecretValue"
        )

        with secrets_boundary(client=failing):
            response = api_ngfw_ssh_url(request, app_id)

        # The Secrets Manager fetch now runs in the bootstrap worker (#929), so
        # the failure surfaces via the polled status, not the initial response.
        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 500
        assert _json(status)["error"] == "Internal server error"

    def test_returns_500_when_signing_secret_is_invalid(self, rf, user, settings, make_ngfw, secrets_boundary):
        # A non-AES-length secret makes the real sign_and_encrypt step raise.
        settings.GUACAMOLE_JSON_AUTH_SECRET = "abcd"  # nosec B105
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with secrets_boundary():
            response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 202
        status = _status_response(rf, user, _json(response)["request_id"])
        assert status.status_code == 500
        assert "Failed to generate SSH URL" in _json(status)["error"]

    def test_returns_503_when_guacamole_not_configured(self, rf, user, settings, make_ngfw, secrets_boundary):
        settings.GUACAMOLE_JSON_AUTH_SECRET = ""
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with secrets_boundary():
            response = api_ngfw_ssh_url(request, app_id)

        assert response.status_code == 503
        assert "not configured" in _json(response)["error"].lower()

    # ---- logging ----------------------------------------------------------

    def test_logs_successful_url_generation(
        self, rf, user, guac_configured, make_ngfw, secrets_boundary, guac_exchange, caplog
    ):
        ngfw = make_ngfw(user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with secrets_boundary(), guac_exchange() as exchange, caplog.at_level(logging.INFO, logger="mission_control"):
            api_ngfw_ssh_url(request, app_id)

        assert len(exchange.requests) == 1
        assert app_id in caplog.text

    def test_logs_permission_denied_errors(self, rf, user, other_user, guac_secret, make_ngfw, caplog):
        ngfw = make_ngfw(user, owner=other_user)
        app_id = str(ngfw.uuid)
        request = _post_request(rf, user, app_id)

        with caplog.at_level(logging.ERROR, logger="mission_control"):
            api_ngfw_ssh_url(request, app_id)

        assert "permission" in caplog.text.lower()
