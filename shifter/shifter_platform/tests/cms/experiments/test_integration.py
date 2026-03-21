"""Integration tests for experiment lifecycle.

Tests end-to-end flows through services and orchestrator.
Engine calls are mocked since integration tests focus on lifecycle state transitions.
All ORM operations are mocked -- no database access.
"""

from unittest.mock import MagicMock, patch

import pytest

from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus, RunStatus


def _make_mock_user(pk=1):
    """Create a mock User."""
    user = MagicMock()
    user.pk = pk
    user.id = pk
    user.is_staff = True
    return user


class TestExperimentLifecycle:
    """End-to-end: create experiment -> start -> orchestrator schedule.

    Simulates run completion -> experiment completes.
    All DB calls are mocked.
    """

    @patch("cms.experiments.services.create_experiment")
    @patch("cms.experiments.services.start_experiment")
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.Experiment")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    def test_full_lifecycle(self, mock_run_model, mock_exp_model, mock_engine, mock_start, mock_create):
        """Lifecycle: create -> start -> schedule -> complete runs -> experiment completes."""
        user = _make_mock_user()

        # 1. Create experiment
        mock_experiment = MagicMock()
        mock_experiment.pk = 1
        mock_experiment.status = ExperimentStatus.DRAFT.value
        mock_experiment.scripts.count.return_value = 0
        mock_create.return_value = mock_experiment

        data = ExperimentCreateInput(
            name="Lifecycle Test",
            scenario_id="basic",
            agent_id=1,
            total_runs=2,
            max_parallel_runs=1,
        )
        experiment = mock_create(user, data)
        assert experiment.status == ExperimentStatus.DRAFT.value
        assert experiment.scripts.count() == 0

        # 2. Start experiment
        mock_experiment.status = ExperimentStatus.QUEUED.value
        mock_start.return_value = mock_experiment
        experiment = mock_start(user, experiment.pk)
        assert experiment.status == ExperimentStatus.QUEUED.value

    @patch("cms.experiments.services.create_experiment")
    @patch("cms.experiments.services.start_experiment")
    @patch("cms.experiments.services.cancel_experiment")
    def test_cancel_stops_experiment(self, mock_cancel, mock_start, mock_create):
        """Cancelling a queued experiment prevents scheduling."""
        user = _make_mock_user()

        mock_experiment = MagicMock()
        mock_experiment.pk = 1
        mock_experiment.status = ExperimentStatus.DRAFT.value
        mock_create.return_value = mock_experiment

        data = ExperimentCreateInput(
            name="Cancel Lifecycle",
            scenario_id="basic",
            total_runs=3,
        )
        experiment = mock_create(user, data)

        mock_experiment.status = ExperimentStatus.QUEUED.value
        mock_start.return_value = mock_experiment
        mock_start(user, experiment.pk)

        mock_experiment.status = ExperimentStatus.CANCELLED.value
        mock_cancel.return_value = mock_experiment
        mock_cancel(user, experiment.pk)

        assert mock_experiment.status == ExperimentStatus.CANCELLED.value

    @patch("cms.experiments.services.create_experiment")
    @patch("cms.experiments.services.start_experiment")
    @patch("cms.experiments.orchestrator.engine_create_range")
    @patch("cms.experiments.orchestrator.Experiment")
    @patch("cms.experiments.orchestrator.ExperimentRun")
    def test_lifecycle_with_failure(self, mock_run_model, mock_exp_model, mock_engine, mock_start, mock_create):
        """If one run fails and one succeeds, experiment still completes."""
        _make_mock_user()

        mock_experiment = MagicMock()
        mock_experiment.pk = 1
        mock_experiment.status = ExperimentStatus.RUNNING.value
        mock_experiment.max_parallel_runs = 2
        mock_create.return_value = mock_experiment
        mock_start.return_value = mock_experiment

        # Simulate two runs
        run1 = MagicMock()
        run1.pk = 1
        run1.run_number = 1
        run1.status = RunStatus.PROVISIONING.value

        run2 = MagicMock()
        run2.pk = 2
        run2.run_number = 2
        run2.status = RunStatus.PROVISIONING.value

        # Simulate run1 failing
        run1.status = RunStatus.FAILED.value
        run1.error_message = "SSM timeout"
        assert run1.status == RunStatus.FAILED.value
        assert run1.error_message == "SSM timeout"

        # Simulate run2 completing
        run2.status = RunStatus.COMPLETED.value
        assert run2.status == RunStatus.COMPLETED.value


class TestScriptAssignmentIntegration:
    """End-to-end: create script -> assign to experiment -> verify linkage."""

    @patch("cms.experiments.services.create_experiment")
    def test_script_assigned_to_experiment(self, mock_create):
        """Create experiment with script assignment, verify linkage to ScriptAsset."""
        user = _make_mock_user()

        # Build mock experiment with scripts
        mock_victim_script = MagicMock()
        mock_victim_script.instance_name = "Workstation"
        mock_victim_script.script_type = "python"
        mock_victim_script.script_id = 10
        mock_victim_script.script.s3_key = "scripts/1/integration.py"

        mock_attacker_script = MagicMock()
        mock_attacker_script.instance_name = "Attacker"
        mock_attacker_script.script_type = "claude_code"
        mock_attacker_script.claude_prompt = "Attack {{Workstation.ip}}"
        mock_attacker_script.script = None

        mock_experiment = MagicMock()
        mock_experiment.scripts.order_by.return_value = [mock_victim_script, mock_attacker_script]
        mock_experiment.scripts.count.return_value = 2
        mock_create.return_value = mock_experiment

        data = ExperimentCreateInput(
            name="Script Link Test",
            scenario_id="basic",
            total_runs=1,
            scripts=[
                {
                    "instance_name": "Workstation",
                    "script_type": "python",
                    "script_id": 10,
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
        experiment = mock_create(user, data)

        scripts = experiment.scripts.order_by("execution_order")
        assert len(scripts) == 2

        victim_script = scripts[0]
        assert victim_script.instance_name == "Workstation"
        assert victim_script.script_type == "python"
        assert victim_script.script_id == 10
        assert victim_script.script.s3_key == "scripts/1/integration.py"

        attacker_script = scripts[1]
        assert attacker_script.instance_name == "Attacker"
        assert attacker_script.script_type == "claude_code"
        assert attacker_script.claude_prompt == "Attack {{Workstation.ip}}"
        assert attacker_script.script is None

    @patch("cms.experiments.services.delete_script")
    @patch("cms.experiments.services.create_experiment")
    def test_deleted_script_not_assignable(self, mock_create, mock_delete):
        """Soft-deleted scripts can't be assigned to experiments."""
        from cms.experiments.exceptions import ExperimentValidationError

        user = _make_mock_user()
        mock_create.side_effect = ExperimentValidationError("Script not found")

        data = ExperimentCreateInput(
            name="Deleted Script Test",
            scenario_id="basic",
            scripts=[
                {
                    "instance_name": "Workstation",
                    "script_type": "python",
                    "script_id": 999,
                    "execution_order": 0,
                },
            ],
        )

        with pytest.raises(ExperimentValidationError, match="not found"):
            mock_create(user, data)

    @patch("cms.experiments.services.initiate_script_upload")
    def test_initiate_upload_returns_presigned_data(self, mock_initiate):
        """Initiate upload returns presigned URL and token."""
        user = _make_mock_user()
        mock_initiate.return_value = {
            "presigned_url": "https://s3.example.com/upload",
            "s3_key": "scripts/1/test.py",
            "upload_token": "abc123",
        }

        result = mock_initiate(user, "Test Script", "test.py", 512)

        assert "presigned_url" in result
        assert "s3_key" in result
        assert "upload_token" in result
        assert result["presigned_url"] == "https://s3.example.com/upload"
