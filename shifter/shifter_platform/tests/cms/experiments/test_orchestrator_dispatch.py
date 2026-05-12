"""Tests for experiment orchestrator command dispatch and artifact collection.

Tests the _dispatch_commands and _collect_artifacts methods which start ECS
tasks to execute scripts on range instances and collect output artifacts.

Logic under test:
- Serializes ScriptCommand list into ECS task payload
- Starts ECS task with correct experiment/run/request context
- Handles ECS configuration missing (graceful degradation)
- Handles ECS task start failures (run transitions to FAILED)
- Artifact collection starts ECS task with "collect" command
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from cms.experiments.orchestrator import ScriptCommand
from cms.experiments.schemas import ExperimentStatus, RunStatus


def _make_mock_run(run_pk=1, status=RunStatus.EXECUTING_VICTIMS.value, request_id=None):
    """Create a mock ExperimentRun."""
    run = MagicMock()
    run.pk = run_pk
    run.run_number = 1
    run.status = status
    run.request_id = request_id or uuid4()
    run.error_message = ""
    run.metadata = None
    return run


def _make_mock_experiment(exp_pk=1, user_pk=1):
    """Create a mock Experiment."""
    exp = MagicMock()
    exp.pk = exp_pk
    exp.user.pk = user_pk
    exp.status = ExperimentStatus.RUNNING.value
    return exp


def _sample_commands():
    """Build sample script commands for testing."""
    return [
        ScriptCommand(
            instance_name="Workstation",
            instance_id="i-abc123",
            script_type="python",
            command="python3 /tmp/script.py",
            execution_order=1,
            script_s3_key="scripts/test.py",
        ),
        ScriptCommand(
            instance_name="Workstation",
            instance_id="i-abc123",
            script_type="claude_code",
            command="claude -p 'Run nmap scan'",
            execution_order=2,
        ),
    ]


class TestDispatchCommands:
    """Tests for _dispatch_commands -- starts ECS tasks for script execution."""

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_starts_ecs_task_with_execute_command(self, mock_exp_model, mock_ecs):
        """Dispatch starts an ECS task with the 'execute' command."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        mock_ecs.assert_called_once()
        call_kwargs = mock_ecs.call_args
        assert call_kwargs[1]["command"] == "execute"

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_passes_experiment_and_run_context(self, mock_exp_model, mock_ecs):
        """ECS task receives correct experiment_id, run_id, request_id."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp = _make_mock_experiment(exp_pk=10)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(run_pk=5)
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["experiment_id"] == exp.pk
        assert call_kwargs["run_id"] == run.pk
        assert call_kwargs["request_id"] == run.request_id

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_serializes_commands_in_payload(self, mock_exp_model, mock_ecs):
        """Commands are serialized as dicts in the ECS task payload."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        payload = mock_ecs.call_args[1]["payload"]
        assert "commands" in payload
        assert payload["ai_execution_policy"]["version"] == "ai-experiment-execution-v1"
        assert len(payload["commands"]) == 2
        assert payload["commands"][0]["instance_id"] == "i-abc123"
        assert payload["commands"][0]["execution_order"] == 1

    @patch("cms.experiments.orchestrator.start_experiment_task", return_value=None)
    @patch("cms.experiments.orchestrator.Experiment")
    def test_ecs_not_configured_fails_run(self, mock_exp_model, mock_ecs):
        """When ECS returns None (not configured), run transitions to FAILED."""
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        run.transition_to.assert_called()
        # The run should have error_message about ECS
        assert "ECS" in run.error_message

    @patch(
        "cms.experiments.orchestrator.start_experiment_task",
        side_effect=Exception("ECS RunTask failed"),
    )
    @patch("cms.experiments.orchestrator.Experiment")
    def test_ecs_failure_fails_run(self, mock_exp_model, mock_ecs):
        """ECS API failure transitions run to FAILED with error details."""
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        run.transition_to.assert_called()
        assert "ECS RunTask failed" in run.error_message

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_stores_task_arn_in_metadata(self, mock_exp_model, mock_ecs):
        """ECS task ARN is stored in run.metadata for debugging."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()
        run.metadata = {}
        commands = _sample_commands()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        assert run.metadata.get("dispatch_task_arn") == "arn:aws:ecs:us-east-2:123:task/abc"


class TestCollectArtifacts:
    """Tests for _collect_artifacts -- starts ECS tasks for artifact collection."""

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_starts_ecs_task_with_collect_command(self, mock_exp_model, mock_ecs):
        """Collection starts an ECS task with the 'collect' command."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(status=RunStatus.COLLECTING.value)

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        mock_ecs.assert_called_once()
        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["command"] == "collect"

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_passes_experiment_and_run_context(self, mock_exp_model, mock_ecs):
        """ECS task receives correct experiment_id, run_id, request_id."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp = _make_mock_experiment(exp_pk=10)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(run_pk=5, status=RunStatus.COLLECTING.value)

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["experiment_id"] == exp.pk
        assert call_kwargs["run_id"] == run.pk
        assert call_kwargs["request_id"] == run.request_id

    @patch("cms.experiments.orchestrator.start_experiment_task", return_value=None)
    @patch("cms.experiments.orchestrator.Experiment")
    def test_ecs_not_configured_fails_run(self, mock_exp_model, mock_ecs):
        """When ECS returns None, run transitions to FAILED."""
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(status=RunStatus.COLLECTING.value)

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        run.transition_to.assert_called()
        assert "ECS" in run.error_message

    @patch(
        "cms.experiments.orchestrator.start_experiment_task",
        side_effect=Exception("Network error"),
    )
    @patch("cms.experiments.orchestrator.Experiment")
    def test_ecs_failure_fails_run(self, mock_exp_model, mock_ecs):
        """ECS failure transitions run to FAILED."""
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(status=RunStatus.COLLECTING.value)

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        run.transition_to.assert_called()
        assert "Network error" in run.error_message

    @patch("cms.experiments.orchestrator.start_experiment_task")
    @patch("cms.experiments.orchestrator.Experiment")
    def test_stores_task_arn_in_metadata(self, mock_exp_model, mock_ecs):
        """ECS task ARN is stored in run.metadata for debugging."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp = _make_mock_experiment()
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run(status=RunStatus.COLLECTING.value)
        run.metadata = {}

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        assert run.metadata.get("collect_task_arn") == "arn:aws:ecs:us-east-2:123:task/xyz"
