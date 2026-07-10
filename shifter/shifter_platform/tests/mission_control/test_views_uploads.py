"""Behavior tests for the presigned-URL agent upload views.

Drives the real upload endpoints with the test client and a real database.
Validation, the session upload-lock, and the error/sanitization paths run fully
first-party (with ``AWS_S3_BUCKET_NAME`` unset, the real S3 helpers raise, so
the views exercise real ``CMSError`` handling). The success round-trip mocks the
AWS SDK (a real cloud boundary) so the presigned-URL and head-object calls are
deterministic.
"""

import json
import time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from botocore.exceptions import ClientError
from django.test import Client, override_settings
from django.urls import reverse

from cms.assets.upload_token import generate_upload_token
from cms.models import OperatingSystem
from mission_control.upload_session import set_upload_in_progress

pytestmark = pytest.mark.django_db

INITIATE = reverse("mission_control:initiate_upload")
COMPLETE = reverse("mission_control:complete_upload")
CANCEL = reverse("mission_control:cancel_upload")


def _post(client, url, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return client.post(url, data=body, content_type="application/json")


def _body(resp):
    return json.loads(resp.content)


def _s3_mock():
    """A boto3 client mock with deterministic presigned-URL + head-object."""
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://s3.example/presigned"
    client.head_object.return_value = {"ContentLength": 100, "ETag": '"abc123"'}
    body = MagicMock()
    body.read.return_value = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
    client.get_object.return_value = {"Body": body}
    return client


def _client_error(code="500"):
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "DeleteObject")


def _upload_token(user, *, s3_key=None):
    return generate_upload_token(
        user_id=user.id,
        s3_key=s3_key or f"agents/{user.id}/agent.msi",
        name="Agent",
        filename="agent.msi",
        os_slug="windows",
        file_size=100,
    )


def _set_upload_lock(client, upload_token):
    session = client.session
    set_upload_in_progress(session, True, upload_token=upload_token)
    session.save()


def _csrf_client(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    response = client.get(reverse("mission_control:agents"))
    assert response.status_code == 200
    return client, client.cookies["csrftoken"].value


class TestInitiateUpload:
    def test_requires_login(self):
        assert _post(Client(), INITIATE, {}).status_code == 401

    def test_returns_400_for_invalid_json(self, authenticated_client):
        client, _ = authenticated_client(email="up-json@example.com")
        resp = _post(client, INITIATE, "not json")
        assert resp.status_code == 400
        assert "Invalid JSON" in _body(resp)["error"]

    @pytest.mark.parametrize(
        "payload,err_substr",
        [
            ({"name": "", "filename": "f", "file_size": 10}, "Agent name"),
            ({"name": "n", "filename": "", "file_size": 10}, "Filename"),
            ({"name": "n", "filename": "f", "file_size": 0}, "file size"),
            ({"name": "n", "filename": "f", "file_size": "x"}, "file size"),
            ({"name": "n", "filename": "f", "file_size": 10, "agent_type": "bogus"}, "Invalid agent"),
        ],
        ids=["name", "filename", "size-zero", "size-not-int", "agent-type"],
    )
    def test_validation_errors(self, authenticated_client, payload, err_substr):
        client, _ = authenticated_client(email="up-val@example.com")
        resp = _post(client, INITIATE, payload)
        assert resp.status_code == 400
        assert err_substr in _body(resp)["error"]

    def test_returns_409_when_upload_already_in_progress(self, authenticated_client):
        client, _ = authenticated_client(email="up-lock@example.com")
        session = client.session
        session["upload_lock"] = {"started_at": time.time()}
        session.save()
        resp = _post(client, INITIATE, {"name": "n", "filename": "a.msi", "file_size": 10})
        assert resp.status_code == 409

    @override_settings(AWS_S3_BUCKET_NAME="")
    def test_real_cms_error_is_sanitized_not_echoed(self, authenticated_client):
        # With no S3 bucket configured the real S3 helper raises, so the view
        # returns an authored literal -- never the raw exception text (guards
        # py/stack-trace-exposure). Pinned via override_settings so the
        # precondition holds regardless of ambient/other-test settings.
        client, _ = authenticated_client(email="up-err@example.com")
        resp = _post(client, INITIATE, {"name": "n", "filename": "agent.msi", "file_size": 10})
        assert resp.status_code == 400
        body = _body(resp)
        assert body["error"] == "Upload could not be initiated"
        assert "\n" not in body["error"] and "\r" not in body["error"]

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket")
    def test_success_returns_presigned_url_and_sets_lock(self, authenticated_client):
        client, _ = authenticated_client(email="up-ok@example.com")
        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, INITIATE, {"name": "Agent", "filename": "/some/dir/agent.msi", "file_size": 100})
        assert resp.status_code == 200
        assert _body(resp)["presigned_url"] == "https://s3.example/presigned"
        # The session lock was set.
        assert "upload_lock" in client.session


class TestCompleteUpload:
    def test_returns_400_for_invalid_json(self, authenticated_client):
        client, _ = authenticated_client(email="comp-json@example.com")
        assert _post(client, COMPLETE, "not json").status_code == 400

    def test_invalid_token_is_rejected_and_clears_lock(self, authenticated_client):
        client, _ = authenticated_client(email="comp-bad@example.com")
        session = client.session
        session["upload_lock"] = {"started_at": time.time()}
        session.save()
        resp = _post(client, COMPLETE, {"upload_token": "not-a-real-token"})
        assert resp.status_code == 400
        # Lock is cleared even on failure.
        assert "upload_lock" not in client.session

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_success_clears_lock(self, authenticated_client):
        client, user = authenticated_client(email="comp-ok@example.com")
        OperatingSystem.objects.get_or_create(
            slug="windows",
            defaults={"name": "Windows", "extensions": [".msi"]},
        )
        token = _upload_token(user)
        _set_upload_lock(client, token)

        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, COMPLETE, {"upload_token": token})

        assert resp.status_code == 200
        body = _body(resp)
        assert body["success"] is True
        assert body["agent_id"]
        assert body["message"] == "Agent 'Agent' uploaded successfully."
        assert "upload_lock" not in client.session

    # The complete success path above drives the real service with only the S3
    # boundary mocked, so response formatting and lock clearing stay pinned.


class TestCancelUpload:
    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_cancel_with_token_clears_matching_lock(self, authenticated_client):
        client, user = authenticated_client(email="cancel-ok@example.com")
        token = _upload_token(user)
        _set_upload_lock(client, token)
        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, CANCEL, {"upload_token": token})
        assert resp.status_code == 200
        assert "upload_lock" not in client.session

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_cancel_with_token_clears_lock_when_storage_cleanup_fails(self, authenticated_client):
        client, user = authenticated_client(email="cancel-cleanup@example.com")
        token = _upload_token(user)
        _set_upload_lock(client, token)
        s3 = _s3_mock()
        s3.delete_object.side_effect = _client_error()
        with patch("boto3.client", return_value=s3):
            resp = _post(client, CANCEL, {"upload_token": token})
        assert resp.status_code == 200
        assert "upload_lock" not in client.session

    def test_cancel_without_token_is_rejected_and_keeps_lock(self, authenticated_client):
        client, user = authenticated_client(email="cancel-notoken@example.com")
        token = _upload_token(user)
        _set_upload_lock(client, token)
        resp = _post(client, CANCEL, {})
        assert resp.status_code == 400
        assert "upload_lock" in client.session

    def test_cancel_invalid_token_is_rejected_and_keeps_lock(self, authenticated_client):
        client, user = authenticated_client(email="cancel-invalid@example.com")
        token = _upload_token(user)
        _set_upload_lock(client, token)
        resp = _post(client, CANCEL, {"upload_token": "not-a-real-token"})
        assert resp.status_code == 400
        assert "upload_lock" in client.session

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_cancel_stale_valid_token_is_rejected_and_keeps_current_lock(self, authenticated_client):
        client, user = authenticated_client(email="cancel-stale@example.com")
        current_token = _upload_token(user, s3_key=f"agents/{user.id}/current.msi")
        stale_token = _upload_token(user, s3_key=f"agents/{user.id}/old.msi")
        _set_upload_lock(client, current_token)
        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, CANCEL, {"upload_token": stale_token})
        assert resp.status_code == 400
        assert "upload_lock" in client.session

    def test_cancel_rejects_invalid_json_and_keeps_lock(self, authenticated_client):
        client, user = authenticated_client(email="cancel-json@example.com")
        token = _upload_token(user)
        _set_upload_lock(client, token)
        resp = _post(client, CANCEL, "not json")
        assert resp.status_code == 400
        assert "upload_lock" in client.session

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_cancel_requires_csrf_for_session_auth(self, django_user_model):
        user = django_user_model.objects.create_user(username="cancel-csrf@example.com")
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600
        session.save()
        token = _upload_token(user)
        _set_upload_lock(client, token)
        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, CANCEL, {"upload_token": token})
        assert resp.status_code == 403
        assert "upload_lock" in client.session

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket", AGENT_UPLOAD_URL_EXPIRES=900)
    def test_cancel_accepts_form_encoded_beacon_with_csrf_token(self, django_user_model):
        user = django_user_model.objects.create_user(username="cancel-beacon@example.com")
        client, csrf_token = _csrf_client(user)
        token = _upload_token(user)
        _set_upload_lock(client, token)
        body = urlencode({"upload_token": token, "csrfmiddlewaretoken": csrf_token})
        with patch("boto3.client", return_value=_s3_mock()):
            resp = client.post(CANCEL, data=body, content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 200
        assert "upload_lock" not in client.session
