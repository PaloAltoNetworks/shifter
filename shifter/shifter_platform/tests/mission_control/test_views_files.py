"""Tests for mission_control.views._files (script upload + delete views)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.pk = 1
    user.email = "u@example.com"
    user.is_authenticated = True
    return user


def _post(rf, path, payload, user):
    body = json.dumps(payload) if not isinstance(payload, str) else payload
    req = rf.post(path, data=body, content_type="application/json")
    req.user = user
    req.session = {}
    return req


def _get(rf, path, user):
    req = rf.get(path)
    req.user = user
    req.session = {}
    return req


# ---------------------------------------------------------------------------
# files (HTML page)
# ---------------------------------------------------------------------------


class TestFilesPage:
    def test_renders_with_scripts(self, rf, mock_user):
        from mission_control.views import files

        scripts = [MagicMock(name="s1"), MagicMock(name="s2")]
        request = _get(rf, "/mc/files/", mock_user)
        with (
            patch("mission_control.views._files.list_scripts", return_value=scripts),
            patch("mission_control.views.render", return_value=HttpResponse("ok")) as render,
        ):
            files(request)
        _r, template, context = render.call_args.args
        assert template == "mission_control/files.html"
        assert context["scripts"] is scripts
        assert context["active_nav"] == "files"


# ---------------------------------------------------------------------------
# file_upload (JSON two-step)
# ---------------------------------------------------------------------------


class TestFileUploadInitiate:
    def test_returns_400_for_invalid_json(self, rf, mock_user):
        from mission_control.views import file_upload

        request = _post(rf, "/mc/api/files/", "not json", mock_user)
        response = file_upload(request)
        assert response.status_code == 400

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
    def test_validation_errors(self, rf, mock_user, payload, err_substr):
        from mission_control.views import file_upload

        request = _post(rf, "/mc/api/files/", payload, mock_user)
        response = file_upload(request)
        assert response.status_code == 400
        assert err_substr in json.loads(response.content)["error"]

    def test_returns_400_when_initiate_raises(self, rf, mock_user):
        from cms.services import ScriptUploadError
        from mission_control.views import file_upload

        request = _post(
            rf,
            "/mc/api/files/",
            {"name": "n", "filename": "x.sh", "file_size": 10},
            mock_user,
        )
        with patch(
            "mission_control.views._files.initiate_script_upload",
            side_effect=ScriptUploadError("nope"),
        ):
            response = file_upload(request)
        assert response.status_code == 400
        # ``str(e)`` is no longer echoed to the response; "nope" doesn't match
        # any classifier keyword, so the authored default is returned.
        assert json.loads(response.content)["error"] == "Upload could not be initiated"

    def test_returns_presigned_payload_with_basename(self, rf, mock_user):
        from mission_control.views import file_upload

        request = _post(
            rf,
            "/mc/api/files/",
            {"name": "n", "filename": "/path/x.sh", "file_size": 10},
            mock_user,
        )
        with patch(
            "mission_control.views._files.initiate_script_upload",
            return_value={"presigned_url": "https://s3/x", "upload_token": "t"},
        ) as init:
            response = file_upload(request)
        assert response.status_code == 200
        # Basename normalisation: only 'x.sh' passed
        assert init.call_args.args[2] == "x.sh"


class TestFileUploadComplete:
    def test_returns_400_when_complete_raises(self, rf, mock_user):
        from cms.services import ScriptUploadError
        from mission_control.views import file_upload

        request = _post(rf, "/mc/api/files/", {"upload_token": "t"}, mock_user)
        with patch(
            "mission_control.views._files.complete_script_upload",
            side_effect=ScriptUploadError("invalid"),
        ):
            response = file_upload(request)
        assert response.status_code == 400

    def test_returns_success_payload(self, rf, mock_user):
        from mission_control.views import file_upload

        script = MagicMock(pk=7, name="myscript")
        script.name = "myscript"
        request = _post(rf, "/mc/api/files/", {"upload_token": "t"}, mock_user)
        with patch(
            "mission_control.views._files.complete_script_upload",
            return_value=script,
        ):
            response = file_upload(request)
        body = json.loads(response.content)
        assert body["success"] is True
        assert body["script_id"] == 7


# ---------------------------------------------------------------------------
# file_delete
# ---------------------------------------------------------------------------


class TestFileDelete:
    def test_redirects_on_success(self, rf, mock_user):
        from mission_control.views import file_delete

        request = _post(rf, "/mc/files/3/delete/", {}, mock_user)
        request._messages = MagicMock()
        with patch("mission_control.views._files.delete_script") as delete:
            response = file_delete(request, 3)
        assert response.status_code == 302
        delete.assert_called_once_with(mock_user, 3)

    def test_redirects_even_on_error(self, rf, mock_user):
        from cms.services import ScriptUploadError
        from mission_control.views import file_delete

        request = _post(rf, "/mc/files/3/delete/", {}, mock_user)
        request._messages = MagicMock()
        with patch(
            "mission_control.views._files.delete_script",
            side_effect=ScriptUploadError("boom"),
        ):
            response = file_delete(request, 3)
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# api_list_scripts (JSON)
# ---------------------------------------------------------------------------


class TestApiListScripts:
    def test_returns_serialized_scripts(self, rf, mock_user):
        from mission_control.views import api_list_scripts

        s1 = MagicMock()
        s1.pk = 1
        s1.name = "a"
        s1.original_filename = "a.sh"
        s2 = MagicMock()
        s2.pk = 2
        s2.name = "b"
        s2.original_filename = "b.sh"
        request = _get(rf, "/mc/api/files/", mock_user)
        with patch("mission_control.views._files.list_scripts", return_value=[s1, s2]):
            response = api_list_scripts(request)
        body = json.loads(response.content)
        assert len(body["scripts"]) == 2
        assert body["scripts"][0]["name"] == "a"
