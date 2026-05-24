"""Tests for mission_control.views._uploads (presigned-URL agent upload flow)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
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


def _post(rf, path, payload, user, *, session=None):
    """Build POST request with session dict attached."""
    body = json.dumps(payload) if not isinstance(payload, str) else payload
    req = rf.post(path, data=body, content_type="application/json")
    req.user = user
    req.session = session if session is not None else {}
    return req


# ---------------------------------------------------------------------------
# initiate_upload
# ---------------------------------------------------------------------------


class TestInitiateUpload:
    def test_returns_409_if_upload_already_in_progress(self, rf, mock_user):
        import time

        from mission_control.views import initiate_upload

        session = {"upload_lock": {"started_at": time.time()}}
        request = _post(rf, "/mc/api/upload/initiate/", {}, mock_user, session=session)
        response = initiate_upload(request)
        assert response.status_code == 409

    def test_returns_400_for_invalid_json(self, rf, mock_user):
        from mission_control.views import initiate_upload

        request = _post(rf, "/mc/api/upload/initiate/", "not json", mock_user)
        response = initiate_upload(request)
        assert response.status_code == 400
        assert "Invalid JSON" in json.loads(response.content)["error"]

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
    def test_validation_errors(self, rf, mock_user, payload, err_substr):
        from mission_control.views import initiate_upload

        request = _post(rf, "/mc/api/upload/initiate/", payload, mock_user)
        response = initiate_upload(request)
        assert response.status_code == 400
        assert err_substr in json.loads(response.content)["error"]

    def test_returns_400_when_cms_raises(self, rf, mock_user):
        from cms.exceptions import CMSError
        from mission_control.views import initiate_upload

        request = _post(
            rf,
            "/mc/api/upload/initiate/",
            {"name": "n", "filename": "f.msi", "file_size": 10},
            mock_user,
        )
        with patch(
            "mission_control.views._uploads.cms_initiate_upload",
            side_effect=CMSError("file too big"),
        ):
            response = initiate_upload(request)
        assert response.status_code == 400
        assert "file too big" in json.loads(response.content)["error"]

    def test_returns_payload_and_sets_lock_on_success(self, rf, mock_user):
        from mission_control.views import initiate_upload

        request = _post(
            rf,
            "/mc/api/upload/initiate/",
            {"name": "n", "filename": "/some/dir/agent.msi", "file_size": 100},
            mock_user,
        )
        with (
            patch(
                "mission_control.views._uploads.cms_initiate_upload",
                return_value={"presigned_url": "https://s3/x", "s3_key": "k", "upload_token": "t"},
            ) as init,
            patch("mission_control.views._uploads.set_upload_in_progress") as lock,
        ):
            response = initiate_upload(request)
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["presigned_url"] == "https://s3/x"
        # filename was basename-normalised
        init.assert_called_once()
        assert init.call_args.args[2] == "agent.msi"
        lock.assert_called_once_with(request.session, True)


# ---------------------------------------------------------------------------
# complete_upload
# ---------------------------------------------------------------------------


class TestCompleteUpload:
    def test_returns_400_for_invalid_json(self, rf, mock_user):
        from mission_control.views import complete_upload

        request = _post(rf, "/mc/api/upload/complete/", "not json", mock_user)
        response = complete_upload(request)
        assert response.status_code == 400

    def test_returns_400_when_cms_raises(self, rf, mock_user):
        from cms.exceptions import CMSError
        from mission_control.views import complete_upload

        request = _post(rf, "/mc/api/upload/complete/", {"upload_token": "t"}, mock_user)
        with (
            patch(
                "mission_control.views._uploads.cms_complete_upload",
                side_effect=CMSError("bad token"),
            ),
            patch("mission_control.views._uploads.set_upload_in_progress") as lock,
        ):
            response = complete_upload(request)
        assert response.status_code == 400
        # Lock cleared even on failure
        lock.assert_called_with(request.session, False)

    def test_returns_success_payload(self, rf, mock_user):
        from mission_control.views import complete_upload

        agent = MagicMock(id=11, name="A1")
        request = _post(rf, "/mc/api/upload/complete/", {"upload_token": "t"}, mock_user)
        with (
            patch("mission_control.views._uploads.cms_complete_upload", return_value=agent),
            patch("mission_control.views._uploads.set_upload_in_progress") as lock,
        ):
            response = complete_upload(request)
        body = json.loads(response.content)
        assert body["success"] is True
        assert body["agent_id"] == 11
        lock.assert_called_with(request.session, False)


# ---------------------------------------------------------------------------
# cancel_upload
# ---------------------------------------------------------------------------


class TestCancelUpload:
    def test_invokes_cms_cancel_when_token_present(self, rf, mock_user):
        from mission_control.views import cancel_upload

        request = _post(rf, "/mc/api/upload/cancel/", {"upload_token": "t"}, mock_user)
        with (
            patch("mission_control.views._uploads.cms_cancel_upload") as cancel,
            patch("mission_control.views._uploads.set_upload_in_progress") as lock,
        ):
            response = cancel_upload(request)
        assert response.status_code == 200
        cancel.assert_called_once()
        lock.assert_called_once_with(request.session, False)

    def test_ignores_cms_error(self, rf, mock_user):
        from cms.exceptions import CMSError
        from mission_control.views import cancel_upload

        request = _post(rf, "/mc/api/upload/cancel/", {"upload_token": "t"}, mock_user)
        with (
            patch("mission_control.views._uploads.cms_cancel_upload", side_effect=CMSError("x")),
            patch("mission_control.views._uploads.set_upload_in_progress"),
        ):
            response = cancel_upload(request)
        assert response.status_code == 200

    def test_skips_cancel_when_token_missing(self, rf, mock_user):
        from mission_control.views import cancel_upload

        request = _post(rf, "/mc/api/upload/cancel/", {}, mock_user)
        with (
            patch("mission_control.views._uploads.cms_cancel_upload") as cancel,
            patch("mission_control.views._uploads.set_upload_in_progress") as lock,
        ):
            cancel_upload(request)
        cancel.assert_not_called()
        lock.assert_called_once_with(request.session, False)

    def test_tolerates_invalid_json_via_sendbeacon(self, rf, mock_user):
        from mission_control.views import cancel_upload

        request = _post(rf, "/mc/api/upload/cancel/", "not json", mock_user)
        with patch("mission_control.views._uploads.set_upload_in_progress"):
            response = cancel_upload(request)
        assert response.status_code == 200
