"""Tests for experiment orchestrator.

Tests the orchestration logic — scheduling, state transitions, completion checks.
Engine calls are mocked since scheduling tests focus on concurrency and state logic.
All DB access is mocked — these are pure-logic tests using plain pytest classes.
"""

from unittest.mock import MagicMock, patch

import pytest

from cms.experiments.orchestrator import ExperimentOrchestrator, ScriptCommand
from cms.experiments.schemas import TERMINAL_RUN_STATUSES, ExperimentStatus, RunStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_experiment(**overrides):
    """Build a mock Experiment with sensible defaults."""
    exp = MagicMock()
    exp.pk = overrides.get("pk", 1)
    exp.status = overrides.get("status", ExperimentStatus.DRAFT.value)
    exp.name = overrides.get("name", "Test Experiment")
    exp.scenario_id = overrides.get("scenario_id", "basic")
    exp.total_runs = overrides.get("total_runs", 3)
    exp.max_parallel_runs = overrides.get("max_parallel_runs", 2)
    exp.started_at = overrides.get("started_at")
    exp.completed_at = overrides.get("completed_at")
    exp.error_message = overrides.get("error_message", "")
    exp.agent = overrides.get("agent")
    exp.user = overrides.get("user", MagicMock(pk=10))
    return exp


def _make_run(**overrides):
    """Build a mock ExperimentRun with sensible defaults."""
    run = MagicMock()
    run.pk = overrides.get("pk", 100)
    run.experiment_id = overrides.get("experiment_id", 1)
    run.run_number = overrides.get("run_number", 1)
    run.status = overrides.get("status", RunStatus.PENDING.value)
    run.request_id = overrides.get("request_id")
    run.error_message = overrides.get("error_message", "")
    run.metadata = overrides.get("metadata")
    run.started_at = overrides.get("started_at")
    run.completed_at = overrides.get("completed_at")
    return run


def _make_script_assignment(**overrides):
    """Build a mock ExperimentScript."""
    sa = MagicMock()
    sa.instance_name = overrides.get("instance_name", "Workstation")
    sa.script_type = overrides.get("script_type", "python")
    sa.execution_order = overrides.get("execution_order", 10)
    sa.claude_prompt = overrides.get("claude_prompt", "")
    script = MagicMock()
    script.s3_key = overrides.get("s3_key", "scripts/test.py")
    sa.script = overrides.get("script", script)
    return sa


# ---------------------------------------------------------------------------
# ScheduleRunsTest
# ---------------------------------------------------------------------------


class TestScheduleRuns:
    """Tests for schedule_runs() — scheduling, max_parallel, transition logic."""

    @patch(
        "django.db.transaction.atomic",
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
    )
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_schedule_transitions_to_running(self, MockExperiment, MockRun, mock_engine, mock_atomic):
        """schedule_runs transitions a QUEUED experiment to RUNNING."""
        exp = _make_experiment(pk=1, status=ExperimentStatus.QUEUED.value)

        # After transition_to(RUNNING), the status changes to RUNNING
        def do_transition(new_status):
            exp.status = new_status.value

        exp.transition_to.side_effect = do_transition

        # select_for_update().get() returns the experiment
        mock_sfu = MagicMock()
        mock_sfu.get.return_value = exp
        MockExperiment.objects.select_for_update.return_value = mock_sfu

        # No active runs
        MockRun.objects.filter.return_value.count.return_value = 0

        # No pending runs to schedule
        pending_qs = MagicMock()
        pending_qs.filter.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[])
        MockRun.objects.select_for_update.return_value = pending_qs

        orch = ExperimentOrchestrator(experiment_id=1)
        orch.schedule_runs()

        # transition_to was called with RUNNING
        exp.transition_to.assert_called_with(ExperimentStatus.RUNNING)

    @patch(
        "django.db.transaction.atomic",
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
    )
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_respects_max_parallel(self, MockExperiment, MockRun, mock_engine, mock_atomic):
        """schedule_runs only schedules up to max_parallel_runs minus active."""
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value, max_parallel_runs=2)

        mock_sfu = MagicMock()
        mock_sfu.get.return_value = exp
        MockExperiment.objects.select_for_update.return_value = mock_sfu

        # 0 active runs
        MockRun.objects.filter.return_value.count.return_value = 0

        # 5 pending runs available, but slots_available = 2
        run1 = _make_run(pk=101, run_number=1)
        run2 = _make_run(pk=102, run_number=2)

        pending_qs = MagicMock()
        pending_qs.filter.return_value.order_by.return_value.__getitem__ = MagicMock(return_value=[run1, run2])
        MockRun.objects.select_for_update.return_value = pending_qs

        orch = ExperimentOrchestrator(experiment_id=1)

        with patch.object(orch, "_request_range_provisioning"):
            scheduled = orch.schedule_runs()

        assert scheduled == 2
        assert run1.transition_to.call_count == 1
        assert run2.transition_to.call_count == 1
        run1.transition_to.assert_called_with(RunStatus.PROVISIONING)
        run2.transition_to.assert_called_with(RunStatus.PROVISIONING)

    @patch(
        "django.db.transaction.atomic",
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
    )
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_schedules_nothing_when_full(self, MockExperiment, MockRun, mock_engine, mock_atomic):
        """schedule_runs returns 0 when active runs fill all slots."""
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value, max_parallel_runs=1)

        mock_sfu = MagicMock()
        mock_sfu.get.return_value = exp
        MockExperiment.objects.select_for_update.return_value = mock_sfu

        # 1 active run, max_parallel=1 → no slots
        MockRun.objects.filter.return_value.count.return_value = 1

        orch = ExperimentOrchestrator(experiment_id=1)
        scheduled = orch.schedule_runs()

        assert scheduled == 0


# ---------------------------------------------------------------------------
# ExperimentCompletionTest
# ---------------------------------------------------------------------------


class TestExperimentCompletion:
    """Tests for _check_experiment_completion — terminal state detection."""

    @patch("cms.experiments.orchestrator.audit_log_system_event")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_all_runs_completed_marks_experiment_completed(self, MockExperiment, MockRun, mock_audit):
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        # All 2 runs are terminal, all completed, 0 failed
        all_runs_qs = MagicMock()
        all_runs_qs.count.return_value = 2
        all_runs_qs.filter.side_effect = lambda **kwargs: self._filter_runs(kwargs, total=2, completed=2, failed=0)
        MockRun.objects.filter.return_value = all_runs_qs

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._check_experiment_completion()

        exp.transition_to.assert_called_once_with(ExperimentStatus.COMPLETED)

    @patch("cms.experiments.orchestrator.audit_log_system_event")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_all_runs_failed_marks_experiment_failed(self, MockExperiment, MockRun, mock_audit):
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        all_runs_qs = MagicMock()
        all_runs_qs.count.return_value = 2
        all_runs_qs.filter.side_effect = lambda **kwargs: self._filter_runs(kwargs, total=2, completed=0, failed=2)
        MockRun.objects.filter.return_value = all_runs_qs

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._check_experiment_completion()

        exp.transition_to.assert_called_once_with(ExperimentStatus.FAILED)
        exp.save.assert_called()

    @patch("cms.experiments.orchestrator.audit_log_system_event")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_mixed_results_marks_completed(self, MockExperiment, MockRun, mock_audit):
        """If some runs succeed and some fail, experiment is still completed (not failed)."""
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        all_runs_qs = MagicMock()
        all_runs_qs.count.return_value = 2
        all_runs_qs.filter.side_effect = lambda **kwargs: self._filter_runs(kwargs, total=2, completed=1, failed=1)
        MockRun.objects.filter.return_value = all_runs_qs

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._check_experiment_completion()

        exp.transition_to.assert_called_once_with(ExperimentStatus.COMPLETED)

    @patch("cms.experiments.orchestrator.audit_log_system_event")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_pending_runs_block_completion(self, MockExperiment, MockRun, mock_audit):
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        # 2 total, but only 1 terminal (1 pending) → terminal_count < total
        all_runs_qs = MagicMock()
        all_runs_qs.count.return_value = 2
        terminal_qs = MagicMock()
        terminal_qs.count.return_value = 1  # only 1 terminal
        all_runs_qs.filter.return_value = terminal_qs
        MockRun.objects.filter.return_value = all_runs_qs

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._check_experiment_completion()

        exp.transition_to.assert_not_called()

    @staticmethod
    def _filter_runs(kwargs, total, completed, failed):
        """Return a mock queryset whose .count() depends on the filter kwargs."""
        qs = MagicMock()
        status_in = kwargs.get("status__in")
        status_exact = kwargs.get("status")

        if status_in is not None:
            # Terminal statuses filter
            terminal_values = {s.value for s in TERMINAL_RUN_STATUSES}
            if set(status_in) == terminal_values:
                qs.count.return_value = completed + failed
            else:
                qs.count.return_value = 0
        elif status_exact == RunStatus.COMPLETED.value:
            qs.count.return_value = completed
        elif status_exact == RunStatus.FAILED.value:
            qs.count.return_value = failed
        else:
            qs.count.return_value = total

        return qs


# ---------------------------------------------------------------------------
# HandleRunFailedTest
# ---------------------------------------------------------------------------


class TestHandleRunFailed:
    """Tests for handle_run_failed — run failure marking."""

    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_marks_run_failed(self, MockExperiment, MockRun):
        run = _make_run(pk=100, status=RunStatus.PROVISIONING.value)
        MockRun.objects.get.return_value = run
        MockRun.DoesNotExist = Exception

        # Mock experiment for refresh/completion check
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        # select_for_update for schedule_runs path (called inside handle_run_failed)
        mock_sfu = MagicMock()
        mock_sfu.get.return_value = exp
        MockExperiment.objects.select_for_update.return_value = mock_sfu

        orch = ExperimentOrchestrator(experiment_id=1)

        with patch.object(orch, "schedule_runs"), patch.object(orch, "_check_experiment_completion"):
            orch.handle_run_failed(100, "Provisioning timed out")

        run.save.assert_called()
        run.transition_to.assert_called_with(RunStatus.FAILED)
        assert run.error_message == "Provisioning timed out"

    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_ignores_already_terminal(self, MockExperiment, MockRun):
        run = _make_run(pk=100, status=RunStatus.COMPLETED.value)
        MockRun.objects.get.return_value = run
        MockRun.DoesNotExist = Exception

        orch = ExperimentOrchestrator(experiment_id=1)
        orch.handle_run_failed(100, "Late failure")

        run.transition_to.assert_not_called()
        assert run.status == RunStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# ConcurrentScheduleRunsTest
# ---------------------------------------------------------------------------


class TestConcurrentScheduleRuns:
    """Verify that concurrent schedule_runs() calls don't over-schedule beyond max_parallel.

    Since we removed DB access, we verify the locking/scheduling logic via mocks.
    """

    @patch(
        "django.db.transaction.atomic",
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
    )
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_concurrent_schedule_respects_max_parallel(self, MockExperiment, MockRun, mock_engine, mock_atomic):
        """Each invocation of schedule_runs respects slot limits independently."""
        exp = _make_experiment(pk=1, status=ExperimentStatus.RUNNING.value, max_parallel_runs=1)

        mock_sfu = MagicMock()
        mock_sfu.get.return_value = exp
        MockExperiment.objects.select_for_update.return_value = mock_sfu

        # First call: 0 active, 1 slot → schedule 1 run
        run1 = _make_run(pk=101, run_number=1)
        # Second call: 1 active, 1 slot → 0 available
        active_counts = iter([0, 1])
        MockRun.objects.filter.return_value.count.side_effect = lambda: next(active_counts)

        pending_results = iter([[run1], []])
        pending_qs = MagicMock()
        pending_qs.filter.return_value.order_by.return_value.__getitem__ = MagicMock(
            side_effect=lambda s: next(pending_results)
        )
        MockRun.objects.select_for_update.return_value = pending_qs

        orch = ExperimentOrchestrator(experiment_id=1)

        with patch.object(orch, "_request_range_provisioning"):
            first = orch.schedule_runs()
            orch.refresh()
            second = orch.schedule_runs()

        assert first == 1
        assert second == 0
        assert first + second <= exp.max_parallel_runs


# ---------------------------------------------------------------------------
# BuildExecutionPlanTest
# ---------------------------------------------------------------------------


class TestBuildExecutionPlan:
    """Tests for _build_execution_plan validation and error handling."""

    @patch("cms.experiments.orchestrator.ExperimentScript")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_raises_on_missing_instance_id(self, MockExperiment, MockScript):
        """Raises ExecutionPlanError when instance has no instance_id key."""
        from cms.experiments.exceptions import ExecutionPlanError

        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(pk=100)

        # Script assignment targeting "Workstation"
        sa = _make_script_assignment(
            instance_name="Workstation",
            script_type="python",
            execution_order=10,
            s3_key="scripts/test.py",
        )
        mock_qs = MagicMock()
        mock_qs.select_related.return_value.order_by.return_value = [sa]
        MockScript.objects.filter.return_value = mock_qs

        provisioned_instances = {
            "Workstation": {"hostname": "ws01"},  # No instance_id!
        }

        orch = ExperimentOrchestrator(experiment_id=1)

        with (
            patch("cms.experiments.orchestrator.build_instance_data", return_value={}),
            pytest.raises(ExecutionPlanError) as exc_info,
        ):
            orch._build_execution_plan(run, provisioned_instances)

        assert str(run.pk) in str(exc_info.value)
        assert "Workstation" in str(exc_info.value)

    @patch("cms.experiments.orchestrator.ExperimentScript")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_raises_on_missing_instance_completely(self, MockExperiment, MockScript):
        """Raises ExecutionPlanError when instance not in provisioned dict."""
        from cms.experiments.exceptions import ExecutionPlanError

        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(pk=100)

        sa = _make_script_assignment(
            instance_name="Workstation",
            script_type="python",
            execution_order=10,
        )
        mock_qs = MagicMock()
        mock_qs.select_related.return_value.order_by.return_value = [sa]
        MockScript.objects.filter.return_value = mock_qs

        # Provisioned data completely missing "Workstation"
        provisioned_instances = {
            "Server": {"instance_id": "i-abc123"},
        }

        orch = ExperimentOrchestrator(experiment_id=1)

        with (
            patch("cms.experiments.orchestrator.build_instance_data", return_value={}),
            pytest.raises(ExecutionPlanError) as exc_info,
        ):
            orch._build_execution_plan(run, provisioned_instances)

        assert "Workstation" in str(exc_info.value)

    @patch("cms.experiments.orchestrator.ExperimentScript")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_builds_successfully_with_all_instances(self, MockExperiment, MockScript):
        """Builds execution plan successfully when all instances present."""
        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(pk=100)

        sa = _make_script_assignment(
            instance_name="Workstation",
            script_type="python",
            execution_order=10,
            s3_key="scripts/test.py",
        )
        mock_qs = MagicMock()
        mock_qs.select_related.return_value.order_by.return_value = [sa]
        MockScript.objects.filter.return_value = mock_qs

        provisioned_instances = {
            "Workstation": {"instance_id": "i-0abcdef12", "hostname": "ws01"},
        }

        orch = ExperimentOrchestrator(experiment_id=1)

        with patch("cms.experiments.orchestrator.build_instance_data", return_value={}):
            plan = orch._build_execution_plan(run, provisioned_instances)

        assert plan.run_id == run.pk
        assert len(plan.victim_commands) == 1
        assert plan.victim_commands[0].instance_id == "i-0abcdef12"


# ---------------------------------------------------------------------------
# IdempotencyTest
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Tests for idempotency checks in dispatch and collection."""

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_dispatch_commands_idempotent(self, MockExperiment, mock_start_task):
        """_dispatch_commands skips dispatch if task ARN already exists."""
        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(
            pk=100,
            request_id="00000000-0000-0000-0000-000000000001",
            metadata={"dispatch_task_arn": "arn:aws:ecs:us-east-2:123:task/existing"},
        )

        commands = [
            ScriptCommand(
                instance_name="Workstation",
                instance_id="i-abc123",
                script_type="python",
                command="echo test",
                execution_order=10,
            )
        ]

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._dispatch_commands(run, commands)

        # Should NOT call start_experiment_task because ARN already exists
        mock_start_task.assert_not_called()

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_collect_artifacts_idempotent(self, MockExperiment, mock_start_task):
        """_collect_artifacts skips collection if task ARN already exists."""
        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(
            pk=100,
            request_id="00000000-0000-0000-0000-000000000002",
            metadata={"collect_task_arn": "arn:aws:ecs:us-east-2:123:task/existing"},
        )

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._collect_artifacts(run)

        # Should NOT call start_experiment_task because ARN already exists
        mock_start_task.assert_not_called()

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_dispatch_proceeds_when_no_arn(self, MockExperiment, mock_start_task):
        """_dispatch_commands proceeds normally when no ARN exists."""
        mock_start_task.return_value = "arn:aws:ecs:us-east-2:123:task/new"

        exp = _make_experiment(pk=1)
        mock_prefetch = MagicMock()
        mock_prefetch.get.return_value = exp
        MockExperiment.objects.prefetch_related.return_value = mock_prefetch

        run = _make_run(
            pk=100,
            request_id="00000000-0000-0000-0000-000000000003",
            metadata={},  # No dispatch_task_arn
        )

        commands = [
            ScriptCommand(
                instance_name="Workstation",
                instance_id="i-abc123",
                script_type="python",
                command="echo test",
                execution_order=10,
            )
        ]

        orch = ExperimentOrchestrator(experiment_id=1)
        orch._dispatch_commands(run, commands)

        # Should call start_experiment_task since no ARN exists
        mock_start_task.assert_called_once()
