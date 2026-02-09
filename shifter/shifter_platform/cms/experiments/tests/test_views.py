"""Tests for experiment views.

Tests HTTP access control, template rendering, and view logic.
No real S3 or infrastructure calls.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.schemas import ExperimentStatus

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class StaffAccessTest(TestCase):
    """Verify all views require staff access."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="view_user", password=TEST_PASSWORD, is_staff=False)
        cls.staff = User.objects.create_user(username="view_staff", password=TEST_PASSWORD, is_staff=True)

    def test_experiment_list_requires_staff(self):
        self.client.login(username="view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 302  # Redirected to login/admin

    def test_experiment_list_staff_ok(self):
        self.client.login(username="view_staff", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:experiment_list"))
        assert resp.status_code == 200

    def test_script_list_requires_staff(self):
        self.client.login(username="view_user", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 302

    def test_script_list_staff_ok(self):
        self.client.login(username="view_staff", password=TEST_PASSWORD)
        resp = self.client.get(reverse("experiments:script_list"))
        assert resp.status_code == 200


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
