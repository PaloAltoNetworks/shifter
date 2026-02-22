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

from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.orchestrator import ExperimentOrchestrator, ScriptCommand
from cms.experiments.schemas import ExperimentStatus, RunStatus

User = get_user_model()

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class DispatchCommandsTest(TestCase):
    """Tests for _dispatch_commands — starts ECS tasks for script execution."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="dispatch_user", password=TEST_PASSWORD, is_staff=True)

    def _create_executing_run(self) -> tuple[Experiment, ExperimentRun]:
        """Create experiment with a run in EXECUTING_VICTIMS state."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Dispatch Test",
            scenario_id="basic",
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        request_id = uuid4()
        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.EXECUTING_VICTIMS.value,
            request_id=request_id,
        )
        return exp, run

    def _sample_commands(self) -> list[ScriptCommand]:
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

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_starts_ecs_task_with_execute_command(self, mock_ecs: object) -> None:
        """Dispatch starts an ECS task with the 'execute' command."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        mock_ecs.assert_called_once()
        call_kwargs = mock_ecs.call_args
        assert call_kwargs[1]["command"] == "execute"

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_passes_experiment_and_run_context(self, mock_ecs: object) -> None:
        """ECS task receives correct experiment_id, run_id, request_id."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["experiment_id"] == exp.pk
        assert call_kwargs["run_id"] == run.pk
        assert call_kwargs["request_id"] == run.request_id

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_serializes_commands_in_payload(self, mock_ecs: object) -> None:
        """Commands are serialized as dicts in the ECS task payload."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        payload = mock_ecs.call_args[1]["payload"]
        assert "commands" in payload
        assert len(payload["commands"]) == 2
        assert payload["commands"][0]["instance_id"] == "i-abc123"
        assert payload["commands"][0]["execution_order"] == 1

    @patch("cms.experiments.orchestrator.start_experiment_task", return_value=None)
    def test_ecs_not_configured_fails_run(self, mock_ecs: object) -> None:
        """When ECS returns None (not configured), run transitions to FAILED."""
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "ECS" in run.error_message

    @patch(
        "cms.experiments.orchestrator.start_experiment_task",
        side_effect=Exception("ECS RunTask failed"),
    )
    def test_ecs_failure_fails_run(self, mock_ecs: object) -> None:
        """ECS API failure transitions run to FAILED with error details."""
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "ECS RunTask failed" in run.error_message

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_stores_task_arn_in_metadata(self, mock_ecs: object) -> None:
        """ECS task ARN is stored in run.metadata for debugging."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/abc"
        exp, run = self._create_executing_run()
        commands = self._sample_commands()

        orch = ExperimentOrchestrator(exp.pk)
        orch._dispatch_commands(run, commands)

        run.refresh_from_db()
        assert run.metadata is not None
        assert run.metadata.get("dispatch_task_arn") == "arn:aws:ecs:us-east-2:123:task/abc"


class CollectArtifactsTest(TestCase):
    """Tests for _collect_artifacts — starts ECS tasks for artifact collection."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="collect_user", password=TEST_PASSWORD, is_staff=True)

    def _create_collecting_run(self) -> tuple[Experiment, ExperimentRun]:
        """Create experiment with a run in COLLECTING state."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Collect Test",
            scenario_id="basic",
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        request_id = uuid4()
        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.COLLECTING.value,
            request_id=request_id,
        )
        return exp, run

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_starts_ecs_task_with_collect_command(self, mock_ecs: object) -> None:
        """Collection starts an ECS task with the 'collect' command."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp, run = self._create_collecting_run()

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        mock_ecs.assert_called_once()
        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["command"] == "collect"

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_passes_experiment_and_run_context(self, mock_ecs: object) -> None:
        """ECS task receives correct experiment_id, run_id, request_id."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp, run = self._create_collecting_run()

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        call_kwargs = mock_ecs.call_args[1]
        assert call_kwargs["experiment_id"] == exp.pk
        assert call_kwargs["run_id"] == run.pk
        assert call_kwargs["request_id"] == run.request_id

    @patch("cms.experiments.orchestrator.start_experiment_task", return_value=None)
    def test_ecs_not_configured_fails_run(self, mock_ecs: object) -> None:
        """When ECS returns None, run transitions to FAILED."""
        exp, run = self._create_collecting_run()

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "ECS" in run.error_message

    @patch(
        "cms.experiments.orchestrator.start_experiment_task",
        side_effect=Exception("Network error"),
    )
    def test_ecs_failure_fails_run(self, mock_ecs: object) -> None:
        """ECS failure transitions run to FAILED."""
        exp, run = self._create_collecting_run()

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "Network error" in run.error_message

    @patch("cms.experiments.orchestrator.start_experiment_task")
    def test_stores_task_arn_in_metadata(self, mock_ecs: object) -> None:
        """ECS task ARN is stored in run.metadata for debugging."""
        mock_ecs.return_value = "arn:aws:ecs:us-east-2:123:task/xyz"
        exp, run = self._create_collecting_run()

        orch = ExperimentOrchestrator(exp.pk)
        orch._collect_artifacts(run)

        run.refresh_from_db()
        assert run.metadata is not None
        assert run.metadata.get("collect_task_arn") == "arn:aws:ecs:us-east-2:123:task/xyz"
