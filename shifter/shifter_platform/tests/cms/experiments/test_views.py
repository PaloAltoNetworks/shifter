"""Tests for experiment views.

Tests HTTP access control, template rendering, and view logic.
No DB access — all ORM operations are mocked.
"""

import json as json_mod
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from cms.experiments.exceptions import ExperimentError, ExperimentValidationError
from cms.experiments.views import (
    experiment_cancel,
    experiment_create,
    experiment_detail,
    experiment_list,
    experiment_start,
    scenario_instances,
    script_list,
)
from shared.auth import THREAT_RESEARCH_GROUP

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def rf():
    """Django RequestFactory."""
    return RequestFactory()


def _make_staff_user():
    """Return a mock staff user that passes threat_research_required."""
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = True
    user.pk = 1
    user.id = 1
    user.groups.filter.return_value.exists.return_value = False
    return user


def _make_regular_user():
    """Return a mock non-staff user that fails threat_research_required."""
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = False
    user.pk = 2
    user.id = 2
    user.groups.filter.return_value.exists.return_value = False
    return user


def _make_threat_research_user():
    """Return a mock non-staff user in the Threat Research group."""
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = False
    user.pk = 3
    user.id = 3

    # The decorator calls user.groups.filter(name=THREAT_RESEARCH_GROUP).exists()
    # We need filter to return a queryset whose .exists() returns True
    # only when called with name=THREAT_RESEARCH_GROUP.
    def _groups_filter(**kwargs):
        qs = MagicMock()
        if kwargs.get("name") == THREAT_RESEARCH_GROUP:
            qs.exists.return_value = True
        else:
            qs.exists.return_value = False
        return qs

    user.groups.filter = _groups_filter
    return user


@pytest.fixture
def staff_user():
    return _make_staff_user()


@pytest.fixture
def regular_user():
    return _make_regular_user()


@pytest.fixture
def threat_user():
    return _make_threat_research_user()


def _get_request(rf, user, path="/"):
    """Build a GET request with user and messages support."""
    request = rf.get(path)
    request.user = user
    request._messages = MagicMock()
    return request


def _post_request(rf, user, path="/", data=None):
    """Build a POST request with user and messages support."""
    request = rf.post(path, data=data or {})
    request.user = user
    request._messages = MagicMock()
    return request


# =============================================================================
# StaffAccessTest — Verify views require staff or Threat Research group
# =============================================================================


class TestStaffAccess:
    """Verify all views require staff or Threat Research group access."""

    def test_experiment_list_requires_authorization(self, rf, regular_user):
        request = _get_request(rf, regular_user)
        resp = experiment_list(request)
        assert resp.status_code == 302
        assert "mission-control" in resp.url

    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.list_experiments")
    def test_experiment_list_staff_ok(self, mock_list, mock_render, rf, staff_user):
        mock_list.return_value = []
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, staff_user)
        resp = experiment_list(request)
        assert resp.status_code == 200

    def test_script_list_requires_authorization(self, rf, regular_user):
        request = _get_request(rf, regular_user)
        resp = script_list(request)
        assert resp.status_code == 302
        assert "mission-control" in resp.url

    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.list_scripts")
    def test_script_list_staff_ok(self, mock_list, mock_render, rf, staff_user):
        mock_list.return_value = []
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, staff_user)
        resp = script_list(request)
        assert resp.status_code == 200

    def test_unauthorized_user_sees_permission_denied_message(self, rf, regular_user):
        request = _get_request(rf, regular_user)
        resp = experiment_list(request)
        assert resp.status_code == 302
        # The decorator calls messages.error with "permission" text
        request._messages.add.assert_called()
        # messages.error calls storage.add(level, message, extra_tags)
        call_args = request._messages.add.call_args
        message_text = str(call_args)
        assert "permission" in message_text.lower()


# =============================================================================
# ThreatResearchAccessTest — Threat Research group has same access as staff
# =============================================================================


class TestThreatResearchAccess:
    """Threat Research group members have the same access as staff."""

    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.list_experiments")
    def test_threat_research_can_access_experiment_list(self, mock_list, mock_render, rf, threat_user):
        mock_list.return_value = []
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, threat_user)
        resp = experiment_list(request)
        assert resp.status_code == 200

    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.list_scripts")
    def test_threat_research_can_access_script_list(self, mock_list, mock_render, rf, threat_user):
        mock_list.return_value = []
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, threat_user)
        resp = script_list(request)
        assert resp.status_code == 200

    def test_regular_user_still_blocked_from_experiment_list(self, rf, regular_user):
        request = _get_request(rf, regular_user)
        resp = experiment_list(request)
        assert resp.status_code == 302
        assert "mission-control" in resp.url

    def test_regular_user_still_blocked_from_script_list(self, rf, regular_user):
        request = _get_request(rf, regular_user)
        resp = script_list(request)
        assert resp.status_code == 302
        assert "mission-control" in resp.url


# =============================================================================
# ExperimentListViewTest — Shows own experiments
# =============================================================================


class TestExperimentListView:
    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.list_experiments")
    def test_shows_own_experiments(self, mock_list, mock_render, rf, staff_user):
        experiment = MagicMock(name="My Experiment")
        mock_list.return_value = [experiment]
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, staff_user)
        resp = experiment_list(request)
        assert resp.status_code == 200
        mock_list.assert_called_once_with(staff_user)
        # The paginated experiments Page is the view's primary output beyond the
        # status code; assert it reaches the template under the "experiments"
        # key (mirrors test_detail_passes_experiment_to_template).
        context = mock_render.call_args[0][2]
        assert "experiments" in context
        assert list(context["experiments"]) == [experiment]


# =============================================================================
# ExperimentDetailViewTest — Detail page and ownership
# =============================================================================


class TestExperimentDetailView:
    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.get_experiment")
    def test_detail_shows_experiment(self, mock_get, mock_render, rf, staff_user):
        exp = MagicMock()
        exp.name = "Detail Test"
        mock_get.return_value = exp
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, staff_user)
        resp = experiment_detail(request, experiment_id=1)
        assert resp.status_code == 200
        mock_get.assert_called_once_with(staff_user, 1)

    @patch("cms.experiments.views.render")
    @patch("cms.experiments.views.services.get_experiment")
    def test_detail_passes_experiment_to_template(self, mock_get, mock_render, rf, staff_user):
        exp = MagicMock()
        exp.name = "Detail Test"
        mock_get.return_value = exp
        mock_render.return_value = HttpResponse(status=200)
        request = _get_request(rf, staff_user)
        experiment_detail(request, experiment_id=1)
        context = mock_render.call_args[0][2]
        assert context["experiment"] is exp

    @patch("cms.experiments.views.services.get_experiment")
    def test_detail_other_user_redirects(self, mock_get, rf, staff_user):
        mock_get.side_effect = ExperimentError("Not found")
        request = _get_request(rf, staff_user)
        resp = experiment_detail(request, experiment_id=999)
        assert resp.status_code == 302


# =============================================================================
# ExperimentStartViewTest — Start experiment
# =============================================================================


class TestExperimentStartView:
    @patch("cms.experiments.views.services.start_experiment")
    def test_start_draft_experiment(self, mock_start, rf, staff_user):
        request = _post_request(rf, staff_user)
        resp = experiment_start(request, experiment_id=1)
        assert resp.status_code == 302
        mock_start.assert_called_once_with(staff_user, 1)

    def test_start_requires_post(self, rf, staff_user):
        request = _get_request(rf, staff_user)
        resp = experiment_start(request, experiment_id=1)
        assert resp.status_code == 405


# =============================================================================
# ExperimentCancelViewTest — Cancel experiment
# =============================================================================


class TestExperimentCancelView:
    @patch("cms.experiments.views.services.cancel_experiment")
    def test_cancel_experiment(self, mock_cancel, rf, staff_user):
        request = _post_request(rf, staff_user)
        resp = experiment_cancel(request, experiment_id=1)
        assert resp.status_code == 302
        mock_cancel.assert_called_once_with(staff_user, 1)

    def test_cancel_requires_post(self, rf, staff_user):
        request = _get_request(rf, staff_user)
        resp = experiment_cancel(request, experiment_id=1)
        assert resp.status_code == 405


# =============================================================================
# ExperimentCreateViewTest — Create experiment form and POST
# =============================================================================


class TestExperimentCreateView:
    @patch("cms.experiments.views.render")
    @patch("cms.scenarios.registry.list_all_scenarios")
    def test_create_get_renders_form(self, mock_scenarios, mock_render, rf, staff_user):
        mock_scenarios.return_value = []
        mock_render.return_value = HttpResponse(b"Create Experiment", status=200)
        request = _get_request(rf, staff_user)
        resp = experiment_create(request)
        assert resp.status_code == 200
        mock_render.assert_called_once()

    @patch("cms.experiments.views.services.create_experiment")
    @patch("cms.scenarios.registry.load_scenario_template")
    def test_create_post_valid(self, mock_load, mock_create, rf, staff_user):
        mock_scenario = MagicMock()
        mock_scenario.instances = []
        mock_load.return_value = mock_scenario
        created_exp = MagicMock()
        created_exp.name = "View Test Exp"
        created_exp.pk = 42
        mock_create.return_value = created_exp
        request = _post_request(
            rf,
            staff_user,
            data={
                "name": "View Test Exp",
                "scenario_id": "basic",
                "total_runs": "2",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        resp = experiment_create(request)
        assert resp.status_code == 302
        mock_create.assert_called_once()

    @patch("cms.experiments.views.services.create_experiment")
    @patch("cms.scenarios.registry.load_scenario_template")
    def test_create_post_invalid_scenario(self, mock_load, mock_create, rf, staff_user):
        mock_load.side_effect = ValueError("Unknown scenario")
        mock_create.return_value = MagicMock(pk=1)
        request = _post_request(
            rf,
            staff_user,
            data={
                "name": "Bad Scenario",
                "scenario_id": "nonexistent",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        resp = experiment_create(request)
        assert resp.status_code == 302

    @patch("cms.experiments.views.services.create_experiment")
    @patch("cms.scenarios.registry.load_scenario_template")
    def test_threat_research_user_blocked_from_hidden_scenario_post(self, mock_load, mock_create, rf, threat_user):
        """Regression for #771: a non-staff Threat Research user must not be
        able to POST a disabled or staff_only scenario_id and have an experiment
        created. The decorator lets the user in; the access check lives in
        services.create_experiment via registry.check_scenario_access.

        The view's POST handler must therefore propagate the service-layer
        rejection as a form redirect, never as a created experiment.
        """
        mock_template = MagicMock()
        mock_template.instances = []
        mock_load.return_value = mock_template
        mock_create.side_effect = ExperimentValidationError(
            "Invalid scenario: Scenario 'hidden-internal' is not available"
        )

        request = _post_request(
            rf,
            threat_user,
            data={
                "name": "Trying hidden",
                "scenario_id": "hidden-internal",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        resp = experiment_create(request)

        # Decorator must have admitted the Threat Research user; the service
        # layer must have been called and must have rejected the request.
        mock_create.assert_called_once()
        # Response is a redirect back to the form, NOT a 200 / detail view.
        assert resp.status_code == 302


# =============================================================================
# ScenarioInstancesViewTest — AJAX scenario instances
# =============================================================================


class TestScenarioInstancesView:
    @patch("cms.experiments.views.services.get_scenario_instances")
    def test_returns_instances(self, mock_get, rf, staff_user):
        mock_get.return_value = [{"name": "victim"}, {"name": "attacker"}]
        request = _get_request(rf, staff_user)
        resp = scenario_instances(request, scenario_id="basic")
        assert resp.status_code == 200
        data = json_mod.loads(resp.content)
        assert "instances" in data
        assert len(data["instances"]) > 0

    @patch("cms.experiments.views.services.get_scenario_instances")
    def test_invalid_scenario_returns_400(self, mock_get, rf, staff_user):
        mock_get.side_effect = ExperimentValidationError("Unknown scenario internal-detail-xyz")
        request = _get_request(rf, staff_user)
        resp = scenario_instances(request, scenario_id="nonexistent_xyz")
        assert resp.status_code == 400
        # py/stack-trace-exposure: raw exception text must not reach the client;
        # the body is an authored, classified message instead.
        data = json_mod.loads(resp.content)
        assert data["error"] == "Invalid scenario request"
        assert "internal-detail-xyz" not in resp.content.decode()


# =============================================================================
# MalformedInputViewTest — Malformed JSON and validation errors
# =============================================================================


class TestMalformedInput:
    """Test malformed JSON in scripts_json POST field."""

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_malformed_scripts_json_shows_error(self, mock_load, rf, staff_user):
        mock_load.return_value = MagicMock(instances=[])
        request = _post_request(
            rf,
            staff_user,
            data={
                "name": "Malformed Test",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "{not valid json",
            },
        )
        resp = experiment_create(request)
        # Should redirect back to create form with error, not 500
        assert resp.status_code == 302

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_empty_name_shows_validation_error(self, mock_load, rf, staff_user):
        mock_load.return_value = MagicMock(instances=[])
        request = _post_request(
            rf,
            staff_user,
            data={
                "name": "",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        resp = experiment_create(request)
        # Pydantic validation error, should redirect with error message
        assert resp.status_code == 302

    @patch("cms.scenarios.registry.load_scenario_template")
    def test_parallel_exceeds_total_shows_error(self, mock_load, rf, staff_user):
        mock_load.return_value = MagicMock(instances=[])
        request = _post_request(
            rf,
            staff_user,
            data={
                "name": "Bad Parallel",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "5",
                "scripts_json": "[]",
            },
        )
        resp = experiment_create(request)
        assert resp.status_code == 302


# =============================================================================
# UnexpectedErrorViewTest — Graceful error handling
# =============================================================================


class TestUnexpectedError:
    @patch("cms.experiments.views.services.list_experiments")
    def test_experiment_list_handles_unexpected_error(self, mock_list, rf, staff_user):
        mock_list.side_effect = RuntimeError("Unexpected")
        request = _get_request(rf, staff_user)
        resp = experiment_list(request)
        assert resp.status_code == 302  # Graceful redirect
