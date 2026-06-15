"""Behavior tests for the experiment-script upload/list/delete views.

Drives the real ``mission_control`` file views with the test client and a real
database. The script views require staff / Threat-Research access; a plain user
is rejected with 403. Validation, the page/list reads, and the error paths run
fully first-party (with ``AWS_S3_BUCKET_NAME`` unset the real S3 helpers raise,
so the views exercise real ``ScriptUploadError`` handling). The initiate success
path mocks the AWS SDK (a real cloud boundary). The complete success path is an
S3 download + content inspection owned by cms.experiments and covered there.
"""

import json
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

FILES_PAGE = reverse("mission_control:files")
FILE_UPLOAD = reverse("mission_control:file_upload")
API_SCRIPTS = reverse("mission_control:api_list_scripts")


@pytest.fixture
def staff_client(authenticated_client, django_user_model) -> Callable[..., tuple]:
    """An authenticated client whose user is staff (grants script access)."""

    def _make(email: str):
        user = django_user_model.objects.create_user(username=email, email=email, is_staff=True)
        return authenticated_client(user=user)

    return _make


def _post(client, url, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return client.post(url, data=body, content_type="application/json")


def _body(resp):
    return json.loads(resp.content)


def _s3_mock():
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://s3.example/presigned"
    return client


class TestScriptAccessControl:
    def test_files_page_requires_login(self):
        assert Client().get(FILES_PAGE).status_code == 302

    def test_non_privileged_user_is_forbidden(self, authenticated_client):
        client, _ = authenticated_client(email="plain@example.com")
        assert client.get(FILES_PAGE).status_code == 403


class TestFilesPage:
    def test_renders_empty_for_new_staff_user(self, staff_client):
        client, _ = staff_client("files-page@example.com")
        response = client.get(FILES_PAGE)
        assert response.status_code == 200
        assert "mission_control/files.html" in [t.name for t in response.templates if t.name]
        assert response.context["active_nav"] == "files"
        assert list(response.context["scripts"]) == []


class TestApiListScripts:
    def test_returns_empty_for_new_staff_user(self, staff_client):
        client, _ = staff_client("files-api@example.com")
        response = client.get(API_SCRIPTS)
        assert response.status_code == 200
        assert _body(response)["scripts"] == []


class TestFileUploadInitiate:
    def test_returns_400_for_invalid_json(self, staff_client):
        client, _ = staff_client("files-json@example.com")
        assert _post(client, FILE_UPLOAD, "not json").status_code == 400

    @pytest.mark.parametrize(
        "payload,err_substr",
        [
            ({"name": "", "filename": "f", "file_size": 10}, "Script name"),
            ({"name": "n", "filename": "", "file_size": 10}, "Filename"),
            ({"name": "n", "filename": "f", "file_size": 0}, "file size"),
            ({"name": "n", "filename": "f", "file_size": "x"}, "file size"),
        ],
        ids=["name", "filename", "size-zero", "size-not-int"],
    )
    def test_validation_errors(self, staff_client, payload, err_substr):
        client, _ = staff_client("files-val@example.com")
        resp = _post(client, FILE_UPLOAD, payload)
        assert resp.status_code == 400
        assert err_substr in _body(resp)["error"]

    @override_settings(AWS_S3_BUCKET_NAME="")
    def test_real_error_is_sanitized_not_echoed(self, staff_client):
        # No S3 bucket configured -> real S3 helper raises -> authored literal.
        # Pinned via override_settings so the precondition holds regardless of
        # ambient/other-test settings.
        client, _ = staff_client("files-err@example.com")
        resp = _post(client, FILE_UPLOAD, {"name": "n", "filename": "x.sh", "file_size": 10})
        assert resp.status_code == 400
        body = _body(resp)
        assert body["error"] == "Upload could not be initiated"
        assert "\n" not in body["error"] and "\r" not in body["error"]

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket")
    def test_success_returns_presigned_url(self, staff_client):
        client, _ = staff_client("files-ok@example.com")
        with patch("boto3.client", return_value=_s3_mock()):
            resp = _post(client, FILE_UPLOAD, {"name": "Script", "filename": "/path/x.py", "file_size": 10})
        assert resp.status_code == 200
        assert _body(resp)["presigned_url"] == "https://s3.example/presigned"


class TestFileUploadComplete:
    def test_invalid_token_rejected(self, staff_client):
        client, _ = staff_client("files-comp@example.com")
        resp = _post(client, FILE_UPLOAD, {"upload_token": "not-a-real-token"})
        assert resp.status_code == 400


class TestFileDelete:
    def test_delete_nonexistent_redirects(self, staff_client):
        client, _ = staff_client("files-del@example.com")
        # delete_script raises ScriptUploadError for a missing script; the view
        # catches it, flashes a message, and redirects.
        resp = client.post(reverse("mission_control:file_delete", args=[999999]))
        assert resp.status_code == 302
        assert resp.url == FILES_PAGE
