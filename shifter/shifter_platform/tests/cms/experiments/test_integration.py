"""Integration tests for experiment lifecycle.

Tests end-to-end flows through services and orchestrator.
Engine calls are mocked since integration tests focus on lifecycle state transitions.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from cms.experiments import services
from cms.experiments.models import ExperimentRun, ScriptAsset
from cms.experiments.orchestrator import ExperimentOrchestrator
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus, RunStatus
from cms.models import AgentConfig, OperatingSystem

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class ExperimentLifecycleTest(TestCase):
    """End-to-end: create experiment -> start -> orchestrator schedule.

    Simulates run completion -> experiment completes.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lifecycle_user", password=TEST_PASSWORD, is_staff=True)
        cls.windows_os = OperatingSystem.objects.get(slug="windows")
        cls.agent = AgentConfig.objects.create(
            user=cls.user,
            name="Lifecycle Agent",
            os=cls.windows_os,
            s3_key="agents/test/lifecycle.msi",
            original_filename="lifecycle.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123",
        )

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_full_lifecycle(self, mock_engine):
        # 1. Create experiment
        data = ExperimentCreateInput(
            name="Lifecycle Test",
            scenario_id="basic",
            agent_id=self.agent.pk,
            total_runs=2,
            max_parallel_runs=1,
        )
        experiment = services.create_experiment(self.user, data)
        assert experiment.status == ExperimentStatus.DRAFT.value
        assert experiment.scripts.count() == 0

        # 2. Start experiment — creates runs, transitions to QUEUED
        experiment = services.start_experiment(self.user, experiment.pk)
        assert experiment.status == ExperimentStatus.QUEUED.value
        assert ExperimentRun.objects.filter(experiment=experiment).count() == 2

        # 3. Orchestrator schedules runs — transitions to RUNNING
        orch = ExperimentOrchestrator(experiment.pk)
        scheduled = orch.schedule_runs()
        assert scheduled == 1  # max_parallel=1

        experiment.refresh_from_db()
        assert experiment.status == ExperimentStatus.RUNNING.value

        # Verify only 1 run is PROVISIONING, 1 still PENDING
        runs = ExperimentRun.objects.filter(experiment=experiment).order_by("run_number")
        assert runs[0].status == RunStatus.PROVISIONING.value
        assert runs[1].status == RunStatus.PENDING.value

        # 4. Simulate first run completing (manually transition through states)
        run1 = runs[0]
        run1.transition_to(RunStatus.EXECUTING_VICTIMS)
        run1.transition_to(RunStatus.EXECUTING_ATTACKER)
        run1.transition_to(RunStatus.COLLECTING)
        run1.transition_to(RunStatus.COMPLETED)

        # 5. Orchestrator schedules next run and checks completion
        orch.refresh()
        orch.schedule_runs()
        orch._check_experiment_completion()

        # Experiment should still be running (run2 not done)
        experiment.refresh_from_db()
        assert experiment.status == ExperimentStatus.RUNNING.value

        # Run 2 should now be PROVISIONING
        runs[1].refresh_from_db()
        assert runs[1].status == RunStatus.PROVISIONING.value

        # 6. Complete run 2
        run2 = runs[1]
        run2.transition_to(RunStatus.EXECUTING_VICTIMS)
        run2.transition_to(RunStatus.EXECUTING_ATTACKER)
        run2.transition_to(RunStatus.COLLECTING)
        run2.transition_to(RunStatus.COMPLETED)

        # 7. Orchestrator detects all runs complete
        orch.refresh()
        orch._check_experiment_completion()

        experiment.refresh_from_db()
        assert experiment.status == ExperimentStatus.COMPLETED.value
        assert experiment.completed_at is not None

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_lifecycle_with_failure(self, mock_engine):
        """If one run fails and one succeeds, experiment still completes."""
        data = ExperimentCreateInput(
            name="Failure Lifecycle",
            scenario_id="basic",
            agent_id=self.agent.pk,
            total_runs=2,
            max_parallel_runs=2,
        )
        experiment = services.create_experiment(self.user, data)
        experiment = services.start_experiment(self.user, experiment.pk)

        orch = ExperimentOrchestrator(experiment.pk)
        scheduled = orch.schedule_runs()
        assert scheduled == 2  # Both scheduled in parallel

        runs = ExperimentRun.objects.filter(experiment=experiment).order_by("run_number")

        # Run 1 fails via handle_run_failed (simulates external failure)
        orch.handle_run_failed(runs[0].pk, "SSM timeout")
        runs[0].refresh_from_db()
        assert runs[0].status == RunStatus.FAILED.value
        assert runs[0].error_message == "SSM timeout"

        # Run 2 succeeds
        runs[1].transition_to(RunStatus.EXECUTING_VICTIMS)
        runs[1].transition_to(RunStatus.EXECUTING_ATTACKER)
        runs[1].transition_to(RunStatus.COLLECTING)
        runs[1].transition_to(RunStatus.COMPLETED)

        orch.refresh()
        orch._check_experiment_completion()

        experiment.refresh_from_db()
        assert experiment.status == ExperimentStatus.COMPLETED.value

    def test_cancel_stops_experiment(self):
        """Cancelling a queued experiment prevents scheduling."""
        data = ExperimentCreateInput(
            name="Cancel Lifecycle",
            scenario_id="basic",
            total_runs=3,
        )
        experiment = services.create_experiment(self.user, data)
        services.start_experiment(self.user, experiment.pk)
        services.cancel_experiment(self.user, experiment.pk)

        experiment.refresh_from_db()
        assert experiment.status == ExperimentStatus.CANCELLED.value

        # Orchestrator should not schedule any runs
        orch = ExperimentOrchestrator(experiment.pk)
        scheduled = orch.schedule_runs()
        assert scheduled == 0


class ScriptAssignmentIntegrationTest(TestCase):
    """End-to-end: create script -> assign to experiment -> verify linkage."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="script_int_user", password=TEST_PASSWORD, is_staff=True)
        cls.script = ScriptAsset.objects.create(
            user=cls.user,
            name="Integration Script",
            s3_key="scripts/1/integration.py",
            original_filename="integration.py",
            file_size_bytes=256,
        )

    def test_script_assigned_to_experiment(self):
        """Create experiment with script assignment, verify linkage to ScriptAsset."""
        data = ExperimentCreateInput(
            name="Script Link Test",
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
        experiment = services.create_experiment(self.user, data)

        # Verify script assignments
        scripts = experiment.scripts.order_by("execution_order")
        assert scripts.count() == 2

        victim_script = scripts[0]
        assert victim_script.instance_name == "Workstation"
        assert victim_script.script_type == "python"
        assert victim_script.script_id == self.script.pk
        assert victim_script.script.s3_key == "scripts/1/integration.py"

        attacker_script = scripts[1]
        assert attacker_script.instance_name == "Attacker"
        assert attacker_script.script_type == "claude_code"
        assert attacker_script.claude_prompt == "Attack {{Workstation.ip}}"
        assert attacker_script.script is None

    def test_deleted_script_not_assignable(self):
        """Soft-deleted scripts can't be assigned to experiments."""
        services.delete_script(self.user, self.script.pk)

        data = ExperimentCreateInput(
            name="Deleted Script Test",
            scenario_id="basic",
            scripts=[
                {
                    "instance_name": "Workstation",
                    "script_type": "python",
                    "script_id": self.script.pk,
                    "execution_order": 0,
                },
            ],
        )
        import pytest

        from cms.experiments.exceptions import ExperimentValidationError

        with pytest.raises(ExperimentValidationError, match="not found"):
            services.create_experiment(self.user, data)

    @patch("cms.experiments.services.generate_script_upload_url")
    def test_initiate_upload_returns_presigned_data(self, mock_generate):
        """Initiate upload returns presigned URL and token."""
        mock_generate.return_value = ("https://s3.example.com/upload", "scripts/1/test.py")

        result = services.initiate_script_upload(self.user, "Test Script", "test.py", 512)

        assert "presigned_url" in result
        assert "s3_key" in result
        assert "upload_token" in result
        assert result["presigned_url"] == "https://s3.example.com/upload"
