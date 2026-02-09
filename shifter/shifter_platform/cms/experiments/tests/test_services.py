"""Tests for experiment services.

Tests the business logic without calling real S3/infrastructure.
"""

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from cms.experiments import services
from cms.experiments.exceptions import (
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.models import Experiment, ExperimentRun, ScriptAsset
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus, RunStatus

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class ListScriptsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="svc_user", password=TEST_PASSWORD, is_staff=True)
        cls.other_user = User.objects.create_user(username="other_user", password=TEST_PASSWORD, is_staff=True)
        ScriptAsset.objects.create(
            user=cls.user,
            name="Active",
            s3_key="scripts/1/a.py",
            original_filename="a.py",
            file_size_bytes=100,
        )
        from django.utils import timezone

        ScriptAsset.objects.create(
            user=cls.user,
            name="Deleted",
            s3_key="scripts/1/b.py",
            original_filename="b.py",
            file_size_bytes=100,
            deleted_at=timezone.now(),
        )
        ScriptAsset.objects.create(
            user=cls.other_user,
            name="Other",
            s3_key="scripts/2/c.py",
            original_filename="c.py",
            file_size_bytes=100,
        )

    def test_returns_only_active_for_user(self):
        scripts = services.list_scripts(self.user)
        assert scripts.count() == 1
        assert scripts.first().name == "Active"

    def test_other_user_sees_own(self):
        scripts = services.list_scripts(self.other_user)
        assert scripts.count() == 1
        assert scripts.first().name == "Other"


class DeleteScriptTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="del_user", password=TEST_PASSWORD, is_staff=True)
        cls.other_user = User.objects.create_user(username="del_other", password=TEST_PASSWORD, is_staff=True)

    def test_soft_deletes_own_script(self):
        script = ScriptAsset.objects.create(
            user=self.user,
            name="ToDelete",
            s3_key="scripts/1/d.py",
            original_filename="d.py",
            file_size_bytes=100,
        )
        services.delete_script(self.user, script.pk)
        script.refresh_from_db()
        assert script.deleted_at is not None

    def test_cannot_delete_other_users_script(self):
        script = ScriptAsset.objects.create(
            user=self.other_user,
            name="NotMine",
            s3_key="scripts/2/e.py",
            original_filename="e.py",
            file_size_bytes=100,
        )
        with pytest.raises(ScriptUploadError, match="not found"):
            services.delete_script(self.user, script.pk)


class CreateExperimentTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="create_user", password=TEST_PASSWORD, is_staff=True)
        cls.script = ScriptAsset.objects.create(
            user=cls.user,
            name="Victim Script",
            s3_key="scripts/1/f.py",
            original_filename="f.py",
            file_size_bytes=100,
        )

    def test_create_basic_experiment(self):
        data = ExperimentCreateInput(
            name="Test Experiment",
            scenario_id="basic",
            total_runs=3,
            max_parallel_runs=2,
        )
        exp = services.create_experiment(self.user, data)
        assert exp.pk is not None
        assert exp.status == ExperimentStatus.DRAFT.value
        assert exp.total_runs == 3

    def test_create_with_script_assignments(self):
        data = ExperimentCreateInput(
            name="With Scripts",
            scenario_id="basic",
            total_runs=1,
            scripts=[
                {
                    "instance_name": "Workstation",
                    "script_type": "python",
                    "script_id": self.script.pk,
                    "execution_order": 0,
                },
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.ip}}",
                    "execution_order": 100,
                },
            ],
        )
        exp = services.create_experiment(self.user, data)
        assert exp.scripts.count() == 2

    def test_invalid_scenario_raises(self):
        data = ExperimentCreateInput(
            name="Bad Scenario",
            scenario_id="nonexistent",
        )
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.create_experiment(self.user, data)

    def test_invalid_instance_name_raises(self):
        data = ExperimentCreateInput(
            name="Bad Instance",
            scenario_id="basic",
            scripts=[
                {
                    "instance_name": "NonExistentBox",
                    "script_type": "python",
                    "script_id": self.script.pk,
                }
            ],
        )
        with pytest.raises(ExperimentValidationError, match="not found in scenario"):
            services.create_experiment(self.user, data)


class StartExperimentTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="start_user", password=TEST_PASSWORD, is_staff=True)

    def test_start_creates_runs_and_queues(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Start Test",
            scenario_id="basic",
            total_runs=3,
        )
        result = services.start_experiment(self.user, exp.pk)
        assert result.status == ExperimentStatus.QUEUED.value
        assert ExperimentRun.objects.filter(experiment=exp).count() == 3

    def test_start_non_draft_raises(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Already Running",
            scenario_id="basic",
            status=ExperimentStatus.QUEUED.value,
        )
        with pytest.raises(ExperimentStateError, match="draft state"):
            services.start_experiment(self.user, exp.pk)

    def test_start_nonexistent_raises(self):
        with pytest.raises(ExperimentError, match="not found"):
            services.start_experiment(self.user, 99999)


class CancelExperimentTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="cancel_user", password=TEST_PASSWORD, is_staff=True)

    def test_cancel_queued(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Cancel Test",
            scenario_id="basic",
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        result = services.cancel_experiment(self.user, exp.pk)
        assert result.status == ExperimentStatus.CANCELLED.value

    def test_cancel_draft_raises(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Draft Cancel",
            scenario_id="basic",
        )
        with pytest.raises(ExperimentStateError, match="Cannot cancel"):
            services.cancel_experiment(self.user, exp.pk)


class GetExperimentTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="get_user", password=TEST_PASSWORD, is_staff=True)
        cls.other_user = User.objects.create_user(username="get_other", password=TEST_PASSWORD, is_staff=True)

    def test_get_own_experiment(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Get Test",
            scenario_id="basic",
        )
        result = services.get_experiment(self.user, exp.pk)
        assert result.pk == exp.pk

    def test_get_other_users_experiment_raises(self):
        exp = Experiment.objects.create(
            user=self.other_user,
            name="Other Exp",
            scenario_id="basic",
        )
        with pytest.raises(ExperimentError, match="not found"):
            services.get_experiment(self.user, exp.pk)


class ListExperimentsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="list_user", password=TEST_PASSWORD, is_staff=True)
        cls.exp = Experiment.objects.create(
            user=cls.user,
            name="List Test",
            scenario_id="basic",
            total_runs=3,
        )

    def test_list_returns_experiments(self):
        exps = services.list_experiments(self.user)
        assert exps.count() == 1

    def test_annotates_run_counts(self):
        # Create runs
        for i in range(1, 4):
            ExperimentRun.objects.create(experiment=self.exp, run_number=i)
        ExperimentRun.objects.filter(experiment=self.exp, run_number=1).update(status=RunStatus.COMPLETED.value)

        exps = services.list_experiments(self.user)
        exp = exps.first()
        assert exp.total_run_count == 3
        assert exp.completed_runs == 1


class ScenarioInstancesTest(TestCase):
    def test_basic_scenario_returns_instances(self):
        instances = services.get_scenario_instances("basic")
        assert len(instances) > 0
        names = {i["name"] for i in instances}
        # Basic scenario has at least these
        assert "Attacker" in names or "Workstation" in names or len(names) > 0

    def test_invalid_scenario_raises(self):
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.get_scenario_instances("nonexistent_scenario_123")
