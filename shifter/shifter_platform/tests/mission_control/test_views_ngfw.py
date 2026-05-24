"""Tests covering NGFW HTML and JSON views (`mission_control/views/_ngfw.py`).

Mirrors the patching style of `test_ngfw_detail.py` /
`test_api_ngfw_ssh_url.py`. All ORM and service calls are mocked.
"""

from __future__ import annotations

import json
from datetime import UTC
from unittest.mock import MagicMock, patch
from uuid import uuid4

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
    user.email = "test@example.com"
    user.is_authenticated = True
    return user


def _post_json(rf, path, payload, user):
    req = rf.post(path, data=json.dumps(payload), content_type="application/json")
    req.user = user
    return req


def _get(rf, path, user):
    req = rf.get(path)
    req.user = user
    return req


# ---------------------------------------------------------------------------
# HTML views: list, wizard, deprovision
# ---------------------------------------------------------------------------


class TestNGFWListView:
    def test_renders_with_ngfws_context(self, rf, mock_user):
        from mission_control.views import ngfw_list

        ngfws = [MagicMock(name="N1"), MagicMock(name="N2")]
        request = _get(rf, "/mc/ngfw/", mock_user)
        with (
            patch("mission_control.views._ngfw.cms_list_ngfws", return_value=ngfws),
            patch("mission_control.views.render", return_value=HttpResponse("ok")) as render,
        ):
            ngfw_list(request)
        _r, template, context = render.call_args.args
        assert template == "mission_control/ngfw/list.html"
        assert context["ngfws"] is ngfws
        assert context["active_nav"] == "ngfw"


class TestNGFWDetailRedirectOnMissing:
    def test_redirects_when_cms_raises_cms_error(self, rf, mock_user):
        from cms.exceptions import CMSError as _BackendCMSError
        from mission_control.views import ngfw_detail

        request = _get(rf, f"/mc/ngfw/{uuid4()}/", mock_user)
        request._messages = MagicMock()
        with patch("mission_control.views.cms_get_ngfw", side_effect=_BackendCMSError("nope")):
            response = ngfw_detail(request, str(uuid4()))
        assert response.status_code == 302
        assert "ngfw" in response.url


class TestNGFWWizardView:
    def test_filters_credentials_by_type_and_expiry(self, rf, mock_user):
        from mission_control.views import ngfw_wizard

        scm_ok = MagicMock(credential_type="scm", is_expired=False)
        scm_expired = MagicMock(credential_type="scm", is_expired=True)
        dp_ok = MagicMock(credential_type="deployment_profile", is_expired=False)
        other = MagicMock(credential_type="other", is_expired=False)

        request = _get(rf, "/mc/ngfw/wizard/", mock_user)
        with (
            patch(
                "mission_control.views._ngfw.cms_list_credentials",
                return_value=[scm_ok, scm_expired, dp_ok, other],
            ),
            patch("mission_control.views.render", return_value=HttpResponse("ok")) as render,
        ):
            ngfw_wizard(request)
        _r, template, context = render.call_args.args
        assert template == "mission_control/ngfw/wizard.html"
        assert context["scm_credentials"] == [scm_ok]
        assert context["deployment_profiles"] == [dp_ok]


class TestNGFWDeprovisionPage:
    def test_renders_when_ngfw_found(self, rf, mock_user):
        from mission_control.views import ngfw_deprovision

        ngfw = MagicMock(name="Box")
        ngfw.name = "Box"
        request = _get(rf, f"/mc/ngfw/{uuid4()}/deprovision/", mock_user)
        with (
            patch("mission_control.views.cms_get_ngfw", return_value=ngfw),
            patch("mission_control.views.render", return_value=HttpResponse("ok")) as render,
        ):
            ngfw_deprovision(request, str(uuid4()))
        _r, template, context = render.call_args.args
        assert template == "mission_control/ngfw/deprovision.html"
        assert context["ngfw"] is ngfw

    def test_redirects_when_missing(self, rf, mock_user):
        from cms.exceptions import CMSError as _BackendCMSError
        from mission_control.views import ngfw_deprovision

        request = _get(rf, f"/mc/ngfw/{uuid4()}/deprovision/", mock_user)
        request._messages = MagicMock()
        with patch("mission_control.views.cms_get_ngfw", side_effect=_BackendCMSError("nope")):
            response = ngfw_deprovision(request, str(uuid4()))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# api_ngfw_create
# ---------------------------------------------------------------------------


class TestApiNGFWCreate:
    def test_returns_201_on_success(self, rf, mock_user):
        from mission_control.views import api_ngfw_create

        ngfw_ref = MagicMock(app_id=uuid4())
        payload = {
            "name": "My NGFW",
            "deployment_profile_id": "5",
            "registration_method": "pin",
            "scm_credential_id": "9",
        }
        request = _post_json(rf, "/mc/api/ngfw/", payload, mock_user)
        with patch("mission_control.views._ngfw.cms_create_ngfw", return_value=ngfw_ref) as create:
            response = api_ngfw_create(request)
        assert response.status_code == 201
        data = json.loads(response.content)
        assert data["status"] == "provisioning"
        call_kwargs = create.call_args.kwargs
        assert call_kwargs["deployment_profile_id"] == 5
        assert call_kwargs["scm_credential_id"] == 9

    def test_returns_400_for_invalid_json(self, rf, mock_user):
        from mission_control.views import api_ngfw_create

        request = rf.post("/mc/api/ngfw/", data="not json", content_type="application/json")
        request.user = mock_user
        response = api_ngfw_create(request)
        assert response.status_code == 400
        assert "Invalid JSON" in json.loads(response.content)["error"]

    def test_returns_400_when_cms_raises(self, rf, mock_user):
        from cms.exceptions import CMSError as _BackendCMSError
        from mission_control.views import api_ngfw_create

        payload = {
            "name": "X",
            "deployment_profile_id": "5",
            "registration_method": "otp",
            "otp_value": "OTP",
            "otp_folder": "F",
        }
        request = _post_json(rf, "/mc/api/ngfw/", payload, mock_user)
        with patch("mission_control.views._ngfw.cms_create_ngfw", side_effect=_BackendCMSError("bad")):
            response = api_ngfw_create(request)
        assert response.status_code == 400
        assert "bad" in json.loads(response.content)["error"]

    def test_returns_400_for_value_error(self, rf, mock_user):
        from mission_control.views import api_ngfw_create

        payload = {
            "name": "X",
            "deployment_profile_id": "5",
            "registration_method": "pin",
        }
        request = _post_json(rf, "/mc/api/ngfw/", payload, mock_user)
        with patch("mission_control.views._ngfw.cms_create_ngfw", side_effect=ValueError("missing")):
            response = api_ngfw_create(request)
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# api_ngfw_list (JSON)
# ---------------------------------------------------------------------------


class TestApiNGFWList:
    def test_returns_serialized_list(self, rf, mock_user):
        from datetime import datetime

        from mission_control.views import api_ngfw_list

        n = MagicMock()
        n.app_id = uuid4()
        n.name = "N1"
        n.status = "ready"
        n.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        n.serial_number = "S1"
        request = _get(rf, "/mc/api/ngfw/", mock_user)
        with patch("mission_control.views._ngfw.cms_list_ngfws", return_value=[n]):
            response = api_ngfw_list(request)
        data = json.loads(response.content)
        assert len(data["ngfws"]) == 1
        assert data["ngfws"][0]["name"] == "N1"
        assert data["ngfws"][0]["serial_number"] == "S1"


# ---------------------------------------------------------------------------
# api_ngfw_destroy
# ---------------------------------------------------------------------------


class TestApiNGFWDestroy:
    def test_returns_ok_on_success(self, rf, mock_user):
        from mission_control.views import api_ngfw_destroy

        app_id = str(uuid4())
        request = _post_json(rf, f"/mc/api/ngfw/{app_id}/destroy/", {"confirm_name": "Box"}, mock_user)
        with patch("mission_control.views._ngfw.cms_destroy_ngfw") as destroy:
            response = api_ngfw_destroy(request, app_id)
        assert response.status_code == 200
        assert json.loads(response.content)["status"] == "deprovisioning"
        destroy.assert_called_once_with(mock_user, app_id, "Box")

    def test_returns_400_for_invalid_json(self, rf, mock_user):
        from mission_control.views import api_ngfw_destroy

        request = rf.post(f"/mc/api/ngfw/{uuid4()}/destroy/", data="x", content_type="application/json")
        request.user = mock_user
        response = api_ngfw_destroy(request, str(uuid4()))
        assert response.status_code == 400

    def test_returns_404_when_cms_says_not_found(self, rf, mock_user):
        from cms.exceptions import CMSError as _BackendCMSError
        from mission_control.views import api_ngfw_destroy

        app_id = str(uuid4())
        request = _post_json(rf, f"/mc/api/ngfw/{app_id}/destroy/", {"confirm_name": "B"}, mock_user)
        with (
            patch(
                "mission_control.views._ngfw.cms_destroy_ngfw",
                side_effect=_BackendCMSError("NGFW not found"),
            ),
            pytest.raises(Exception) as exc_info,
        ):
            api_ngfw_destroy(request, app_id)
        # Http404 raised
        from django.http import Http404

        assert isinstance(exc_info.value, Http404)

    def test_returns_400_for_other_cms_errors(self, rf, mock_user):
        from cms.exceptions import CMSError as _BackendCMSError
        from mission_control.views import api_ngfw_destroy

        app_id = str(uuid4())
        request = _post_json(rf, f"/mc/api/ngfw/{app_id}/destroy/", {"confirm_name": "B"}, mock_user)
        with patch(
            "mission_control.views._ngfw.cms_destroy_ngfw",
            side_effect=_BackendCMSError("attached ranges"),
        ):
            response = api_ngfw_destroy(request, app_id)
        assert response.status_code == 400

    def test_returns_400_for_value_error(self, rf, mock_user):
        from mission_control.views import api_ngfw_destroy

        app_id = str(uuid4())
        request = _post_json(rf, f"/mc/api/ngfw/{app_id}/destroy/", {"confirm_name": "wrong"}, mock_user)
        with patch(
            "mission_control.views._ngfw.cms_destroy_ngfw",
            side_effect=ValueError("name mismatch"),
        ):
            response = api_ngfw_destroy(request, app_id)
        assert response.status_code == 400
