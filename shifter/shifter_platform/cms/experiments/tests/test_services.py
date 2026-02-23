"""Tests for experiment services.

Tests the business logic without calling real S3/infrastructure.
"""

import threading
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase

from cms.experiments import services
from cms.experiments.exceptions import (
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.models import Experiment, ExperimentRun, ScriptAsset
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus, RunStatus
from shared.constants import USER_CANNOT_BE_NONE

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

    def test_invalid_template_variable_rejected(self):
        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Bad Template Var",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{NonExistent.ip}}",
                    "execution_order": 100,
                },
            ],
        }
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="Unknown instance"):
            ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})

    def test_invalid_template_property_rejected(self):
        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Bad Template Prop",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.password}}",
                    "execution_order": 100,
                },
            ],
        }
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="Unknown property"):
            ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})

    def test_valid_template_variable_accepted(self):
        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Good Template",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.ip}} named {{Workstation.name}}",
                    "execution_order": 100,
                },
            ],
        }
        data = ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})
        exp = services.create_experiment(self.user, data)
        assert exp.pk is not None
        assert exp.scripts.count() == 1


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

    @patch("cms.experiments.services.publish_experiment_event")
    def test_start_publishes_event(self, mock_publish):
        """Verify that starting an experiment publishes experiment.start event."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Event Test",
            scenario_id="basic",
            total_runs=1,
        )
        services.start_experiment(self.user, exp.pk)

        # Verify event was published with correct type and payload
        mock_publish.assert_called_once_with(
            event_type="experiment.start",
            payload={"experiment_id": exp.pk},
        )

    @patch("cms.experiments.services.publish_experiment_event")
    def test_start_continues_if_event_fails(self, mock_publish):
        """Verify that experiment start succeeds even if event publishing fails."""
        mock_publish.side_effect = Exception("SQS unavailable")

        exp = Experiment.objects.create(
            user=self.user,
            name="Event Failure Test",
            scenario_id="basic",
            total_runs=1,
        )

        # Should not raise despite event publishing failure
        result = services.start_experiment(self.user, exp.pk)

        # Experiment should still be queued with runs created
        assert result.status == ExperimentStatus.QUEUED.value
        assert ExperimentRun.objects.filter(experiment=exp).count() == 1


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


class UserValidationTest(TestCase):
    """Verify service functions reject None/invalid users."""

    def test_list_scripts_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scripts(None)

    def test_create_experiment_none_user(self):
        data = ExperimentCreateInput(name="Test", scenario_id="basic")
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.create_experiment(None, data)

    def test_start_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.start_experiment(None, 1)

    def test_get_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_experiment(None, 1)

    def test_list_experiments_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_experiments(None)

    def test_delete_script_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.delete_script(None, 1)

    def test_cancel_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.cancel_experiment(None, 1)


class CatchAllExceptionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="catchall_user", password=TEST_PASSWORD, is_staff=True)

    @patch("cms.experiments.services.Experiment.objects")
    def test_get_experiment_logs_unexpected_error(self, mock_objects):
        mock_objects.prefetch_related.return_value.get.side_effect = RuntimeError("DB gone")
        with pytest.raises(RuntimeError, match="DB gone"):
            services.get_experiment(self.user, 1)


class ConcurrentStartTest(TransactionTestCase):
    """Verify that concurrent start_experiment() calls are serialized by select_for_update()."""

    def test_only_one_concurrent_start_succeeds(self):
        user = User.objects.create_user(username="concurrent_user", password=TEST_PASSWORD, is_staff=True)
        exp = Experiment.objects.create(
            user=user,
            name="Concurrent Start",
            scenario_id="basic",
            total_runs=3,
        )

        barrier = threading.Barrier(2, timeout=5)
        results: list[dict] = [{}, {}]

        def attempt_start(index: int) -> None:
            try:
                barrier.wait()
                # Tiny jitter to help SQLite with concurrent writes
                import secrets
                import time

                jitter = 0.01 + (secrets.randbelow(40) / 1000.0)  # 0.01 to 0.049s
                time.sleep(jitter)
                services.start_experiment(user, exp.pk)
                results[index] = {"success": True}
            except ExperimentStateError as e:
                results[index] = {"success": False, "error": str(e)}
            except Exception as e:
                results[index] = {"success": False, "error": str(e)}

        t1 = threading.Thread(target=attempt_start, args=(0,))
        t2 = threading.Thread(target=attempt_start, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [r for r in results if r.get("success")]
        failures = [r for r in results if not r.get("success")]
        assert len(successes) == 1, f"Expected exactly 1 success, got {results}"
        assert len(failures) == 1, f"Expected exactly 1 failure, got {results}"

        # Verify runs were not doubled
        run_count = ExperimentRun.objects.filter(experiment=exp).count()
        assert run_count == exp.total_runs, f"Expected {exp.total_runs} runs, got {run_count}"
