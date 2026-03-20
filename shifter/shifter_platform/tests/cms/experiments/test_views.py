"""Tests for experiment views.

Tests HTTP access control, template rendering, and view logic.
No real S3 or infrastructure calls.
"""

from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.schemas import ExperimentStatus
from shared.auth import THREAT_RESEARCH_GROUP

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class StaffAccessTest(TestCase):
    """Verify all views require staff or Threat Research group access."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="view_user", password=TEST_PASSWORD, is_staff=False)
        cls.staff = User.objects.create_user(username="view_staff", password=TEST_PASSWORD, is_staff=True)

    def test_experiment_list_requires_authorization(self):
        self.client.login(username="view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 302
        assert resp.url == reverse("mission_control:dashboard")

    def test_experiment_list_staff_ok(self):
        self.client.login(username="view_staff", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 200

    def test_script_list_requires_authorization(self):
        self.client.login(username="view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 302
        assert resp.url == reverse("mission_control:dashboard")

    def test_script_list_staff_ok(self):
        self.client.login(username="view_staff", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 200

    def test_unauthorized_user_sees_permission_denied_message(self):
        self.client.login(username="view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"), follow=True)
        assert resp.status_code == 200
        msgs = list(resp.context["messages"])
        assert any("permission" in str(m).lower() for m in msgs)


class ThreatResearchAccessTest(TestCase):
    """Threat Research group members have the same access as staff."""

    @classmethod
    def setUpTestData(cls):
        cls.regular_user = User.objects.create_user(username="tr_regular", password=TEST_PASSWORD, is_staff=False)
        cls.threat_user = User.objects.create_user(username="tr_threat", password=TEST_PASSWORD, is_staff=False)
        group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
        cls.threat_user.groups.add(group)

    def test_threat_research_can_access_experiment_list(self):
        self.client.login(username="tr_threat", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 200

    def test_threat_research_can_access_script_list(self):
        self.client.login(username="tr_threat", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 200

    def test_regular_user_still_blocked_from_experiment_list(self):
        self.client.login(username="tr_regular", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 302
        assert resp.url == reverse("mission_control:dashboard")

    def test_regular_user_still_blocked_from_script_list(self):
        self.client.login(username="tr_regular", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 302
        assert resp.url == reverse("mission_control:dashboard")


class ExperimentListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="list_view_user", password=TEST_PASSWORD, is_staff=True)
        cls.other = User.objects.create_user(username="list_other", password=TEST_PASSWORD, is_staff=True)
        cls.exp = Experiment.objects.create(
            user=cls.user,
            name="My Experiment",
            scenario_id="basic",
        )
        Experiment.objects.create(
            user=cls.other,
            name="Other Experiment",
            scenario_id="basic",
        )

    def test_shows_own_experiments(self):
        self.client.login(username="list_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 200
        assert b"My Experiment" in resp.content
        assert b"Other Experiment" not in resp.content


class ExperimentDetailViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="detail_user", password=TEST_PASSWORD, is_staff=True)
        cls.other = User.objects.create_user(username="detail_other", password=TEST_PASSWORD, is_staff=True)
        cls.exp = Experiment.objects.create(
            user=cls.user,
            name="Detail Test",
            scenario_id="basic",
            total_runs=3,
        )
        for i in range(1, 4):
            ExperimentRun.objects.create(experiment=cls.exp, run_number=i)

    def test_detail_shows_experiment(self):
        self.client.login(username="detail_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_detail", args=[self.exp.pk]))
        assert resp.status_code == 200
        assert b"Detail Test" in resp.content

    def test_detail_shows_runs(self):
        self.client.login(username="detail_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_detail", args=[self.exp.pk]))
        assert resp.status_code == 200
        assert b"pending" in resp.content

    def test_detail_other_user_redirects(self):
        self.client.login(username="detail_other", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_detail", args=[self.exp.pk]))
        assert resp.status_code == 302  # Redirected because not found for other user


class ExperimentStartViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="start_view_user", password=TEST_PASSWORD, is_staff=True)

    def test_start_draft_experiment(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Start Test",
            scenario_id="basic",
            total_runs=2,
        )
        self.client.login(username="start_view_user", password=TEST_PASSWORD)
        resp = self.client.post(reverse("experiments:experiment_start", args=[exp.pk]))
        assert resp.status_code == 302  # Redirect to detail
        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.QUEUED.value

    def test_start_requires_post(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Start GET",
            scenario_id="basic",
        )
        self.client.login(username="start_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_start", args=[exp.pk]))
        assert resp.status_code == 405


class ExperimentCancelViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="cancel_view_user", password=TEST_PASSWORD, is_staff=True)

    def test_cancel_queued_experiment(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Cancel Test",
            scenario_id="basic",
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        self.client.login(username="cancel_view_user", password=TEST_PASSWORD)
        resp = self.client.post(reverse("experiments:experiment_cancel", args=[exp.pk]))
        assert resp.status_code == 302
        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.CANCELLED.value

    def test_cancel_requires_post(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Cancel GET",
            scenario_id="basic",
        )
        self.client.login(username="cancel_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_cancel", args=[exp.pk]))
        assert resp.status_code == 405


class ExperimentCreateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="create_view_user", password=TEST_PASSWORD, is_staff=True)

    def test_create_get_renders_form(self):
        self.client.login(username="create_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_create"))
        assert resp.status_code == 200
        assert b"Create Experiment" in resp.content

    def test_create_post_valid(self):
        self.client.login(username="create_view_user", password=TEST_PASSWORD)
        resp = self.client.post(
            reverse("experiments:experiment_create"),
            {
                "name": "View Test Exp",
                "scenario_id": "basic",
                "total_runs": "2",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        assert resp.status_code == 302  # Redirect to detail
        assert Experiment.objects.filter(name="View Test Exp").exists()

    def test_create_post_invalid_scenario(self):
        self.client.login(username="create_view_user", password=TEST_PASSWORD)
        resp = self.client.post(
            reverse("experiments:experiment_create"),
            {
                "name": "Bad Scenario",
                "scenario_id": "nonexistent",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        assert resp.status_code == 302  # Redirect back with error


class ScenarioInstancesViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="scenario_view_user", password=TEST_PASSWORD, is_staff=True)

    def test_returns_instances(self):
        self.client.login(username="scenario_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:scenario_instances", args=["basic"]))
        assert resp.status_code == 200
        data = resp.json()
        assert "instances" in data
        assert len(data["instances"]) > 0

    def test_invalid_scenario_returns_400(self):
        self.client.login(username="scenario_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:scenario_instances", args=["nonexistent_xyz"]))
        assert resp.status_code == 400


class MalformedInputViewTest(TestCase):
    """5.8: Test malformed JSON in scripts_json POST field."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="malform_user", password=TEST_PASSWORD, is_staff=True)

    def test_malformed_scripts_json_shows_error(self):
        self.client.login(username="malform_user", password=TEST_PASSWORD)
        resp = self.client.post(
            reverse("experiments:experiment_create"),
            {
                "name": "Malformed Test",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "{not valid json",
            },
        )
        # Should redirect back to create form with error, not 500
        assert resp.status_code == 302

    def test_empty_name_shows_validation_error(self):
        self.client.login(username="malform_user", password=TEST_PASSWORD)
        resp = self.client.post(
            reverse("experiments:experiment_create"),
            {
                "name": "",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "1",
                "scripts_json": "[]",
            },
        )
        # Pydantic validation error, should redirect with error message
        assert resp.status_code == 302

    def test_parallel_exceeds_total_shows_error(self):
        self.client.login(username="malform_user", password=TEST_PASSWORD)
        resp = self.client.post(
            reverse("experiments:experiment_create"),
            {
                "name": "Bad Parallel",
                "scenario_id": "basic",
                "total_runs": "1",
                "max_parallel_runs": "5",
                "scripts_json": "[]",
            },
        )
        assert resp.status_code == 302


class UnexpectedErrorViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="error_view_user", password=TEST_PASSWORD, is_staff=True)

    @patch("cms.experiments.views.services.list_experiments")
    def test_experiment_list_handles_unexpected_error(self, mock_list):
        mock_list.side_effect = RuntimeError("Unexpected")
        self.client.login(username="error_view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 302  # Graceful redirect
