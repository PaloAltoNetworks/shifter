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

import pytest
from django.test import Client, override_settings
from django.urls import reverse

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
    return client


class TestInitiateUpload:
    def test_requires_login(self):
        assert _post(Client(), INITIATE, {}).status_code == 302

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

    # The complete success path is an end-to-end S3 download + MSI content
    # inspection owned by cms.assets (covered by its own suites); the view's
    # parse/delegate/format/lock behavior is covered by the error path above.


class TestCancelUpload:
    def test_cancel_with_token_clears_lock(self, authenticated_client):
        client, _ = authenticated_client(email="cancel-ok@example.com")
        session = client.session
        session["upload_lock"] = {"started_at": time.time()}
        session.save()
        resp = _post(client, CANCEL, {"upload_token": "anything"})
        assert resp.status_code == 200
        assert "upload_lock" not in client.session

    def test_cancel_without_token_still_ok(self, authenticated_client):
        client, _ = authenticated_client(email="cancel-notoken@example.com")
        assert _post(client, CANCEL, {}).status_code == 200

    def test_cancel_tolerates_invalid_json(self, authenticated_client):
        client, _ = authenticated_client(email="cancel-json@example.com")
        assert _post(client, CANCEL, "not json").status_code == 200
