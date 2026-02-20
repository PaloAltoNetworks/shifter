"""Tests for experiment orchestrator.

Tests the orchestration logic — scheduling, state transitions, completion checks.
Engine calls are mocked since scheduling tests focus on concurrency and state logic.
"""

import threading
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.orchestrator import ExperimentOrchestrator
from cms.experiments.schemas import ExperimentStatus, RunStatus
from cms.models import AgentConfig, OperatingSystem

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class ScheduleRunsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="orch_user", password=TEST_PASSWORD, is_staff=True)
        cls.windows_os = OperatingSystem.objects.get(slug="windows")
        cls.agent = AgentConfig.objects.create(
            user=cls.user,
            name="Schedule Test Agent",
            os=cls.windows_os,
            s3_key="agents/test/agent.msi",
            original_filename="agent.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123",
        )

    def _create_queued_experiment(self, total_runs: int = 3, max_parallel: int = 2) -> Experiment:
        """Helper to create a queued experiment with pending runs."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Orch Test",
            scenario_id="basic",
            agent=self.agent,
            total_runs=total_runs,
            max_parallel_runs=max_parallel,
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        for i in range(1, total_runs + 1):
            ExperimentRun.objects.create(experiment=exp, run_number=i)
        return exp

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_schedule_transitions_to_running(self, mock_engine):
        exp = self._create_queued_experiment()
        orch = ExperimentOrchestrator(exp.pk)
        orch.schedule_runs()
        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.RUNNING.value

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_respects_max_parallel(self, mock_engine):
        exp = self._create_queued_experiment(total_runs=5, max_parallel=2)
        orch = ExperimentOrchestrator(exp.pk)
        scheduled = orch.schedule_runs()
        assert scheduled == 2
        provisioning = ExperimentRun.objects.filter(
            experiment=exp,
            status=RunStatus.PROVISIONING.value,
        ).count()
        assert provisioning == 2
        pending = ExperimentRun.objects.filter(
            experiment=exp,
            status=RunStatus.PENDING.value,
        ).count()
        assert pending == 3

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_schedules_nothing_when_full(self, mock_engine):
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
        cls.user = User.objects.create_user(username="comp_user", password=TEST_PASSWORD, is_staff=True)

    def test_all_runs_completed_marks_experiment_completed(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Complete Test",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone

        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        ExperimentRun.objects.create(experiment=exp, run_number=1, status=RunStatus.COMPLETED.value)
        ExperimentRun.objects.create(experiment=exp, run_number=2, status=RunStatus.COMPLETED.value)

        orch = ExperimentOrchestrator(exp.pk)
        orch._check_experiment_completion()

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.COMPLETED.value
        assert exp.completed_at is not None

    def test_all_runs_failed_marks_experiment_failed(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Fail Test",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
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
            user=self.user,
            name="Mixed Test",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
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
            user=self.user,
            name="Not Done",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
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
        cls.user = User.objects.create_user(username="fail_user", password=TEST_PASSWORD, is_staff=True)

    def test_marks_run_failed(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Fail Run",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone

        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.PROVISIONING.value,
        )
        ExperimentRun.objects.create(
            experiment=exp,
            run_number=2,
            status=RunStatus.PENDING.value,
        )

        orch = ExperimentOrchestrator(exp.pk)
        orch.handle_run_failed(run.pk, "Provisioning timed out")

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert run.error_message == "Provisioning timed out"

    def test_ignores_already_terminal(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Already Done",
            scenario_id="basic",
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone

        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.COMPLETED.value,
        )

        orch = ExperimentOrchestrator(exp.pk)
        orch.handle_run_failed(run.pk, "Late failure")

        run.refresh_from_db()
        assert run.status == RunStatus.COMPLETED.value  # Unchanged


class ConcurrentScheduleRunsTest(TransactionTestCase):
    """Verify that concurrent schedule_runs() calls don't over-schedule beyond max_parallel."""

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_concurrent_schedule_respects_max_parallel(self, mock_engine):
        user = User.objects.create_user(username="conc_orch_user", password=TEST_PASSWORD, is_staff=True)
        # TransactionTestCase truncates DB, so data migration fixtures are gone.
        # Create OperatingSystem directly.
        windows_os, _ = OperatingSystem.objects.get_or_create(
            slug="windows",
            defaults={"name": "Windows", "extensions": [".msi", ".exe"]},
        )
        agent = AgentConfig.objects.create(
            user=user,
            name="Conc Test Agent",
            os=windows_os,
            s3_key="agents/conc/agent.msi",
            original_filename="agent.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123",
        )
        exp = Experiment.objects.create(
            user=user,
            name="Concurrent Schedule",
            scenario_id="basic",
            agent=agent,
            total_runs=4,
            max_parallel_runs=1,
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        for i in range(1, 5):
            ExperimentRun.objects.create(experiment=exp, run_number=i)

        barrier = threading.Barrier(2, timeout=5)
        results: list[int] = [0, 0]

        def attempt_schedule(index: int) -> None:
            try:
                orch = ExperimentOrchestrator(exp.pk)
                barrier.wait()
                results[index] = orch.schedule_runs()
            except Exception:
                results[index] = -1

        t1 = threading.Thread(target=attempt_schedule, args=(0,))
        t2 = threading.Thread(target=attempt_schedule, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        total_scheduled = results[0] + results[1]
        # With max_parallel=1, at most 1 run should be in PROVISIONING
        provisioning_count = ExperimentRun.objects.filter(
            experiment=exp,
            status=RunStatus.PROVISIONING.value,
        ).count()
        assert provisioning_count <= exp.max_parallel_runs, (
            f"Expected at most {exp.max_parallel_runs} provisioning, got {provisioning_count}"
        )
        assert total_scheduled <= exp.max_parallel_runs, (
            f"Expected at most {exp.max_parallel_runs} scheduled total, got {total_scheduled}"
        )
