"""Tests for experiment orchestrator.

Tests the orchestration logic — scheduling, state transitions, completion checks.
No mocking of infrastructure (S3, SSM, ECS).
"""

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from experiments.models import Experiment, ExperimentRun, ExperimentScript, ScriptAsset
from experiments.orchestrator import ExperimentOrchestrator
from experiments.schemas import ExperimentStatus, RunStatus, ScriptType


class ScheduleRunsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="orch_user", password="test", is_staff=True)

    def _create_queued_experiment(self, total_runs: int = 3, max_parallel: int = 2) -> Experiment:
        """Helper to create a queued experiment with pending runs."""
        exp = Experiment.objects.create(
            user=self.user, name="Orch Test", scenario_id="basic",
            total_runs=total_runs, max_parallel_runs=max_parallel,
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        for i in range(1, total_runs + 1):
            ExperimentRun.objects.create(experiment=exp, run_number=i)
        return exp

    def test_schedule_transitions_to_running(self):
        exp = self._create_queued_experiment()
        orch = ExperimentOrchestrator(exp.pk)
        orch.schedule_runs()
        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.RUNNING.value

    def test_respects_max_parallel(self):
        exp = self._create_queued_experiment(total_runs=5, max_parallel=2)
        orch = ExperimentOrchestrator(exp.pk)
        scheduled = orch.schedule_runs()
        assert scheduled == 2
        provisioning = ExperimentRun.objects.filter(
            experiment=exp, status=RunStatus.PROVISIONING.value,
        ).count()
        assert provisioning == 2
        pending = ExperimentRun.objects.filter(
            experiment=exp, status=RunStatus.PENDING.value,
        ).count()
        assert pending == 3

    def test_schedules_nothing_when_full(self):
        exp = self._create_queued_experiment(total_runs=2, max_parallel=1)
        orch = ExperimentOrchestrator(exp.pk)
        orch.schedule_runs()  # Schedules 1

        # Try again — should schedule 0 because 1 is already active
        orch.refresh()
        scheduled = orch.schedule_runs()
        assert scheduled == 0


class ExperimentCompletionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="comp_user", password="test", is_staff=True)

    def test_all_runs_completed_marks_experiment_completed(self):
        exp = Experiment.objects.create(
            user=self.user, name="Complete Test", scenario_id="basic",
            total_runs=2, max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run1 = ExperimentRun.objects.create(experiment=exp, run_number=1, status=RunStatus.COMPLETED.value)
        run2 = ExperimentRun.objects.create(experiment=exp, run_number=2, status=RunStatus.COMPLETED.value)

        orch = ExperimentOrchestrator(exp.pk)
        orch._check_experiment_completion()

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.COMPLETED.value
        assert exp.completed_at is not None

    def test_all_runs_failed_marks_experiment_failed(self):
        exp = Experiment.objects.create(
            user=self.user, name="Fail Test", scenario_id="basic",
            total_runs=2, max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        ExperimentRun.objects.create(experiment=exp, run_number=1, status=RunStatus.FAILED.value)
        ExperimentRun.objects.create(experiment=exp, run_number=2, status=RunStatus.FAILED.value)

        orch = ExperimentOrchestrator(exp.pk)
        orch._check_experiment_completion()

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.FAILED.value

    def test_mixed_results_marks_completed(self):
        """If some runs succeed and some fail, experiment is still completed (not failed)."""
        exp = Experiment.objects.create(
            user=self.user, name="Mixed Test", scenario_id="basic",
            total_runs=2, max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        ExperimentRun.objects.create(experiment=exp, run_number=1, status=RunStatus.COMPLETED.value)
        ExperimentRun.objects.create(experiment=exp, run_number=2, status=RunStatus.FAILED.value)

        orch = ExperimentOrchestrator(exp.pk)
        orch._check_experiment_completion()

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.COMPLETED.value

    def test_pending_runs_block_completion(self):
        exp = Experiment.objects.create(
            user=self.user, name="Not Done", scenario_id="basic",
            total_runs=2, max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        ExperimentRun.objects.create(experiment=exp, run_number=1, status=RunStatus.COMPLETED.value)
        ExperimentRun.objects.create(experiment=exp, run_number=2, status=RunStatus.PENDING.value)

        orch = ExperimentOrchestrator(exp.pk)
        orch._check_experiment_completion()

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.RUNNING.value  # Still running


class HandleRunFailedTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="fail_user", password="test", is_staff=True)

    def test_marks_run_failed(self):
        exp = Experiment.objects.create(
            user=self.user, name="Fail Run", scenario_id="basic",
            total_runs=2, max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run = ExperimentRun.objects.create(
            experiment=exp, run_number=1, status=RunStatus.PROVISIONING.value,
        )
        ExperimentRun.objects.create(
            experiment=exp, run_number=2, status=RunStatus.PENDING.value,
        )

        orch = ExperimentOrchestrator(exp.pk)
        orch.handle_run_failed(run.pk, "Provisioning timed out")

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert run.error_message == "Provisioning timed out"

    def test_ignores_already_terminal(self):
        exp = Experiment.objects.create(
            user=self.user, name="Already Done", scenario_id="basic",
            total_runs=1, max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone
        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run = ExperimentRun.objects.create(
            experiment=exp, run_number=1, status=RunStatus.COMPLETED.value,
        )

        orch = ExperimentOrchestrator(exp.pk)
        orch.handle_run_failed(run.pk, "Late failure")

        run.refresh_from_db()
        assert run.status == RunStatus.COMPLETED.value  # Unchanged
