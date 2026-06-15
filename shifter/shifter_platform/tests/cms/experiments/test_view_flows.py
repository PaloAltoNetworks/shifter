"""Branch coverage for the decomposed experiment views.

Drives the script/experiment/download/ajax views in ``cms.experiments.views``
(including the S1142-extracted ``_complete_script_upload_post`` /
``_initiate_script_upload_post`` / ``_handle_script_upload_post`` /
``_validate_experiment_create_input`` / ``_handle_experiment_create_post``
helpers) through ``RequestFactory`` with the service layer mocked at source.
No DB access — all ORM/service work is mocked (matches ``test_views.py``).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse
from django.urls import reverse

from cms.experiments.exceptions import ArtifactError, ExperimentError, ExperimentValidationError, ScriptUploadError

RENDER = "cms.experiments.views.render"
SVC = "cms.experiments.views.services"


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def _staff_user():
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = True
    user.pk = 1
    user.id = 1
    user.groups.filter.return_value.exists.return_value = False
    return user


@pytest.fixture
def staff_user():
    return _staff_user()


def _get(rf, user, **kwargs):
    request = rf.get("/", **kwargs)
    request.user = user
    request._messages = MagicMock()
    return request


def _post(rf, user, data=None):
    request = rf.post("/", data=data or {})
    request.user = user
    request._messages = MagicMock()
    return request


class TestScriptViewFlows:
    def test_script_list_error_redirects(self, rf, staff_user):
        from cms.experiments.views import script_list

        with patch(f"{SVC}.list_scripts", side_effect=RuntimeError("boom")):
            resp = script_list(_get(rf, staff_user))
        assert resp.status_code == 302

    def test_script_upload_get(self, rf, staff_user):
        from cms.experiments.views import script_upload

        with patch(RENDER, return_value=HttpResponse(status=200)):
            resp = script_upload(_get(rf, staff_user))
        assert resp.status_code == 200

    def test_script_upload_method_not_allowed(self, rf, staff_user):
        from cms.experiments.views import script_upload

        request = rf.put("/")
        request.user = staff_user
        request._messages = MagicMock()
        resp = script_upload(request)
        assert resp.status_code == 405

    def test_script_upload_complete_success(self, rf, staff_user):
        from cms.experiments.views import script_upload

        script = MagicMock()
        script.name = "demo"
        with patch(f"{SVC}.complete_script_upload", return_value=script):
            resp = script_upload(_post(rf, staff_user, data={"upload_token": "tok"}))
        assert resp.status_code == 302

    def test_script_upload_complete_error(self, rf, staff_user):
        from cms.experiments.views import script_upload

        with patch(f"{SVC}.complete_script_upload", side_effect=ScriptUploadError("bad token")):
            resp = script_upload(_post(rf, staff_user, data={"upload_token": "tok"}))
        assert resp.status_code == 302

    def test_script_upload_initiate_success(self, rf, staff_user):
        from cms.experiments.views import script_upload

        with patch(f"{SVC}.initiate_script_upload", return_value={"url": "https://x"}):
            resp = script_upload(_post(rf, staff_user, data={"name": "n", "filename": "f.py", "file_size": "10"}))
        assert resp.status_code == 200
        assert json.loads(resp.content)["url"] == "https://x"

    def test_script_upload_initiate_invalid_size(self, rf, staff_user):
        from cms.experiments.views import script_upload

        resp = script_upload(_post(rf, staff_user, data={"name": "n", "filename": "f.py", "file_size": "abc"}))
        assert resp.status_code == 400

    def test_script_upload_initiate_error(self, rf, staff_user):
        from cms.experiments.views import script_upload

        # ScriptUploadError is frequently raised from inner exceptions
        # (e.g. `raise ScriptUploadError(f"Failed to generate upload URL: {e}") from e`),
        # so str(e) can carry internal detail. py/stack-trace-exposure: the response
        # body must be an authored, classified message, not the raw exception text.
        err = ScriptUploadError("Failed to generate upload URL: s3://internal-secret-xyz")
        with patch(f"{SVC}.initiate_script_upload", side_effect=err):
            resp = script_upload(_post(rf, staff_user, data={"name": "n", "filename": "f.py", "file_size": "10"}))
        assert resp.status_code == 400
        assert json.loads(resp.content)["error"] == "Upload could not be initiated"
        assert "internal-secret-xyz" not in resp.content.decode()

    def test_script_upload_unexpected_error(self, rf, staff_user):
        from cms.experiments.views import script_upload

        with patch(f"{SVC}.initiate_script_upload", side_effect=RuntimeError("boom")):
            resp = script_upload(_post(rf, staff_user, data={"name": "n", "filename": "f.py", "file_size": "10"}))
        assert resp.status_code == 302

    def test_script_delete_success(self, rf, staff_user):
        from cms.experiments.views import script_delete

        with patch(f"{SVC}.delete_script", return_value=None):
            resp = script_delete(_post(rf, staff_user), script_id=1)
        assert resp.status_code == 302

    def test_script_delete_upload_error(self, rf, staff_user):
        from cms.experiments.views import script_delete

        with patch(f"{SVC}.delete_script", side_effect=ScriptUploadError("nope")):
            resp = script_delete(_post(rf, staff_user), script_id=1)
        assert resp.status_code == 302

    def test_script_delete_unexpected_error(self, rf, staff_user):
        from cms.experiments.views import script_delete

        with patch(f"{SVC}.delete_script", side_effect=RuntimeError("boom")):
            resp = script_delete(_post(rf, staff_user), script_id=1)
        assert resp.status_code == 302


class TestExperimentViewFlows:
    def test_experiment_list_error_redirects(self, rf, staff_user):
        from cms.experiments.views import experiment_list

        with patch(f"{SVC}.list_experiments", side_effect=RuntimeError("boom")):
            resp = experiment_list(_get(rf, staff_user))
        assert resp.status_code == 302

    def test_experiment_create_get(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        with (
            patch("cms.scenarios.registry.list_all_scenarios", return_value=[]),
            patch(RENDER, return_value=HttpResponse(status=200)),
        ):
            resp = experiment_create(_get(rf, staff_user))
        assert resp.status_code == 200

    def test_experiment_create_method_not_allowed(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        request = rf.put("/")
        request.user = staff_user
        request._messages = MagicMock()
        resp = experiment_create(request)
        assert resp.status_code == 405

    def test_experiment_create_post_success(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        experiment = MagicMock(pk=7)
        experiment.name = "E"
        with (
            patch("cms.experiments.views._validate_experiment_create_input", return_value=MagicMock()),
            patch(f"{SVC}.create_experiment", return_value=experiment),
        ):
            resp = experiment_create(_post(rf, staff_user, data={"name": "E"}))
        assert resp.status_code == 302

    def test_experiment_create_post_validation_error(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        # Invalid scripts_json triggers ExperimentValidationError inside the validator.
        resp = experiment_create(_post(rf, staff_user, data={"scripts_json": "{not json"}))
        assert resp.status_code == 302

    def test_experiment_create_post_value_error(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        # A non-integer agent_id raises a non-pydantic ValueError in the validator
        # (the scenario load is stubbed so execution reaches the int() conversion).
        with patch("cms.scenarios.registry.load_scenario_template", side_effect=ValueError("no scenario")):
            resp = experiment_create(_post(rf, staff_user, data={"scripts_json": "[]", "agent_id": "not-an-int"}))
        assert resp.status_code == 302

    def test_experiment_create_post_unexpected_error(self, rf, staff_user):
        from cms.experiments.views import experiment_create

        with (
            patch("cms.experiments.views._validate_experiment_create_input", return_value=MagicMock()),
            patch(f"{SVC}.create_experiment", side_effect=RuntimeError("boom")),
        ):
            resp = experiment_create(_post(rf, staff_user, data={"name": "E"}))
        assert resp.status_code == 302

    def test_experiment_detail_success(self, rf, staff_user):
        from cms.experiments.views import experiment_detail

        with (
            patch(f"{SVC}.get_experiment", return_value=MagicMock()),
            patch(RENDER, return_value=HttpResponse(status=200)),
        ):
            resp = experiment_detail(_get(rf, staff_user), experiment_id=1)
        assert resp.status_code == 200

    def test_experiment_detail_not_found(self, rf, staff_user):
        from cms.experiments.views import experiment_detail

        with patch(f"{SVC}.get_experiment", side_effect=ExperimentError("nf")):
            resp = experiment_detail(_get(rf, staff_user), experiment_id=1)
        assert resp.status_code == 302

    def test_experiment_detail_unexpected_error(self, rf, staff_user):
        from cms.experiments.views import experiment_detail

        with patch(f"{SVC}.get_experiment", side_effect=RuntimeError("boom")):
            resp = experiment_detail(_get(rf, staff_user), experiment_id=1)
        assert resp.status_code == 302

    @pytest.mark.parametrize("side", [None, ExperimentError("x"), RuntimeError("boom")])
    def test_experiment_start(self, rf, staff_user, side):
        from cms.experiments.views import experiment_start

        kw = {"return_value": None} if side is None else {"side_effect": side}
        with patch(f"{SVC}.start_experiment", **kw):
            resp = experiment_start(_post(rf, staff_user), experiment_id=1)
        assert resp.status_code == 302

    @pytest.mark.parametrize("side", [None, ExperimentError("x"), RuntimeError("boom")])
    def test_experiment_cancel(self, rf, staff_user, side):
        from cms.experiments.views import experiment_cancel

        kw = {"return_value": None} if side is None else {"side_effect": side}
        with patch(f"{SVC}.cancel_experiment", **kw):
            resp = experiment_cancel(_post(rf, staff_user), experiment_id=1)
        assert resp.status_code == 302


class TestDownloadAjaxFlows:
    # Every branch of the download views returns a 302, so status_code alone
    # cannot tell a correct success redirect (to the presigned URL) from an
    # error-fallback redirect (to a detail/list page). Each branch therefore
    # asserts resp["Location"] to pin which URL the user is actually sent to.
    @pytest.mark.parametrize(
        ("side", "expected_location"),
        [
            (None, "https://x/bundle"),
            (ArtifactError("x"), reverse("experiments:experiment_detail", kwargs={"experiment_id": 1})),
            (RuntimeError("boom"), reverse("experiments:experiment_list")),
        ],
    )
    def test_experiment_download(self, rf, staff_user, side, expected_location):
        from cms.experiments.views import experiment_download

        kw = {"return_value": "https://x/bundle"} if side is None else {"side_effect": side}
        with patch(f"{SVC}.get_bundle_download_url", **kw):
            resp = experiment_download(_get(rf, staff_user), experiment_id=1)
        assert resp.status_code == 302
        assert resp["Location"] == expected_location

    @pytest.mark.parametrize(
        ("side", "expected_location"),
        [
            (None, "https://x/a"),
            (ArtifactError("x"), reverse("experiments:experiment_detail", kwargs={"experiment_id": 1})),
            (RuntimeError("boom"), reverse("experiments:experiment_list")),
        ],
    )
    def test_artifact_download(self, rf, staff_user, side, expected_location):
        from cms.experiments.views import artifact_download

        kw = {"return_value": "https://x/a"} if side is None else {"side_effect": side}
        with patch(f"{SVC}.get_artifact_download_url", **kw):
            resp = artifact_download(_get(rf, staff_user), experiment_id=1, run_number=1, artifact_id=2)
        assert resp.status_code == 302
        assert resp["Location"] == expected_location

    def test_scenario_instances_success(self, rf, staff_user):
        from cms.experiments.views import scenario_instances

        with patch(f"{SVC}.get_scenario_instances", return_value=["a", "b"]):
            resp = scenario_instances(_get(rf, staff_user), scenario_id="s")
        assert resp.status_code == 200
        assert json.loads(resp.content)["instances"] == ["a", "b"]

    def test_scenario_instances_validation_error(self, rf, staff_user):
        from cms.experiments.views import scenario_instances

        with patch(f"{SVC}.get_scenario_instances", side_effect=ExperimentValidationError("bad")):
            resp = scenario_instances(_get(rf, staff_user), scenario_id="s")
        assert resp.status_code == 400

    def test_scenario_instances_unexpected_error(self, rf, staff_user):
        from cms.experiments.views import scenario_instances

        with patch(f"{SVC}.get_scenario_instances", side_effect=RuntimeError("boom")):
            resp = scenario_instances(_get(rf, staff_user), scenario_id="s")
        assert resp.status_code == 500
