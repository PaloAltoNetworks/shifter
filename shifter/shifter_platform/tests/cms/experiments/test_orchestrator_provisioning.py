"""Tests for experiment orchestrator range provisioning bridge.

Tests the _request_range_provisioning method which connects the experiment
system to the engine's range provisioning pipeline. This is the critical
bridge that makes experiments functional.

Logic under test:
- Hydrates experiment scenario with agent details into a RangeSpec
- Creates CMS Request + RangeInstance tracking records
- Calls engine.create_range to trigger ECS provisioning
- Stores request_id on ExperimentRun for event correlation
- Handles missing agents, invalid scenarios, and engine failures gracefully
"""

from unittest.mock import patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.test import TestCase

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.orchestrator import ExperimentOrchestrator
from cms.experiments.schemas import ExperimentStatus, RunStatus
from cms.models import AgentConfig, OperatingSystem, RangeInstance, Request

User = get_user_model()

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class RequestRangeProvisioningTest(TestCase):
    """Tests for _request_range_provisioning — the experiment-to-engine bridge."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="prov_user", password=TEST_PASSWORD, is_staff=True)
        cls.windows_os = OperatingSystem.objects.get(slug="windows")
        cls.linux_os = OperatingSystem.objects.get(slug="linux-debian")

    def _create_agent(self, os_obj: OperatingSystem, name: str = "Test Agent") -> AgentConfig:
        """Create an AgentConfig for testing."""
        return AgentConfig.objects.create(
            user=self.user,
            name=name,
            os=os_obj,
            s3_key=f"agents/{self.user.pk}/{name.lower().replace(' ', '_')}.msi",
            original_filename=f"{name.lower()}.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123def456",
        )

    def _create_provisioning_run(
        self,
        scenario_id: str = "basic",
        agent: AgentConfig | None = None,
    ) -> tuple[Experiment, ExperimentRun]:
        """Create an experiment with a single run in PROVISIONING state."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Provisioning Test",
            scenario_id=scenario_id,
            agent=agent,
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.PROVISIONING.value,
        )
        return exp, run

    # -----------------------------------------------------------------
    # Core provisioning flow
    # -----------------------------------------------------------------

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_creates_cms_request_record(self, mock_engine: object) -> None:
        """Provisioning creates a CMS Request for engine correlation."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        # A CMS Request should exist linked to this run
        run.refresh_from_db()
        assert run.request_id is not None
        request = Request.objects.get(request_id=run.request_id)
        assert request.user == self.user

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_stores_request_id_on_run(self, mock_engine: object) -> None:
        """Provisioning stores request_id on ExperimentRun for correlation."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        assert run.request_id is not None
        assert isinstance(run.request_id, UUID)

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_creates_range_instance_record(self, mock_engine: object) -> None:
        """Provisioning creates a RangeInstance for CMS tracking."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        ri = RangeInstance.objects.get(request__request_id=run.request_id)
        assert ri.scenario_id == "basic"
        assert ri.user_id == self.user.pk
        assert ri.agent == agent

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_calls_engine_create_range(self, mock_engine: object) -> None:
        """Provisioning calls engine.create_range with a valid RequestSpec."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_engine.assert_called_once()
        request_spec = mock_engine.call_args[0][0]
        assert request_spec.user_id == self.user.pk
        assert len(request_spec.items) == 1

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_range_spec_has_correct_scenario_id(self, mock_engine: object) -> None:
        """The RangeSpec passed to engine has the experiment's scenario_id."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(scenario_id="basic", agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        request_spec = mock_engine.call_args[0][0]
        range_spec = request_spec.items[0]
        assert range_spec.scenario_id == "basic"

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_range_spec_contains_hydrated_instances(self, mock_engine: object) -> None:
        """The RangeSpec contains properly hydrated instances with agent details."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(scenario_id="basic", agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        request_spec = mock_engine.call_args[0][0]
        range_spec = request_spec.items[0]
        instances = range_spec.all_instances
        assert len(instances) == 2  # basic scenario: attacker + workstation
        victim = next(i for i in instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.s3_key == agent.s3_key

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_range_instance_stores_range_spec_json(self, mock_engine: object) -> None:
        """RangeInstance.range_spec stores the hydrated spec as JSON."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        ri = RangeInstance.objects.get(request__request_id=run.request_id)
        assert ri.range_spec is not None
        assert ri.range_spec["scenario_id"] == "basic"

    # -----------------------------------------------------------------
    # Scenario without agent (e.g., cortex_deployment_experience)
    # -----------------------------------------------------------------

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_provisions_scenario_without_agent(self, mock_engine: object) -> None:
        """Scenarios that don't require agents can be provisioned without one."""
        # cortex_deployment_experience has xdr_agent=false on all instances
        exp, run = self._create_provisioning_run(scenario_id="cortex_deployment_experience", agent=None)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_engine.assert_called_once()
        run.refresh_from_db()
        assert run.request_id is not None

    # -----------------------------------------------------------------
    # Error handling
    # -----------------------------------------------------------------

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_invalid_scenario_fails_run(self, mock_engine: object) -> None:
        """Invalid scenario_id transitions run to FAILED with error message."""
        exp, run = self._create_provisioning_run(scenario_id="nonexistent")

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "nonexistent" in run.error_message.lower() or "not found" in run.error_message.lower()
        mock_engine.assert_not_called()

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_missing_required_agent_fails_run(self, mock_engine: object) -> None:
        """Scenario requiring agent but experiment has none → run FAILED."""
        # basic scenario requires an agent (has xdr_agent=true instances)
        exp, run = self._create_provisioning_run(scenario_id="basic", agent=None)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert run.error_message != ""
        mock_engine.assert_not_called()

    @patch("cms.experiments.orchestrator.engine_create_range", side_effect=Exception("ECS down"))
    def test_engine_failure_fails_run(self, mock_engine: object) -> None:
        """Engine failure transitions run to FAILED with error details."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "ECS down" in run.error_message

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_deleted_agent_fails_run(self, mock_engine: object) -> None:
        """Soft-deleted agent fails the run."""
        from django.utils import timezone

        agent = self._create_agent(self.windows_os)
        agent.deleted_at = timezone.now()
        agent.save(update_fields=["deleted_at"])
        exp, run = self._create_provisioning_run(scenario_id="basic", agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        mock_engine.assert_not_called()

    # -----------------------------------------------------------------
    # AD Attack Lab scenario (multi-instance with domain controller)
    # -----------------------------------------------------------------

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_ad_attack_lab_produces_three_instances(self, mock_engine: object) -> None:
        """AD Attack Lab hydrates with attacker, DC, and victim."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(scenario_id="ad_attack_lab", agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        request_spec = mock_engine.call_args[0][0]
        range_spec = request_spec.items[0]
        instances = range_spec.all_instances
        assert len(instances) == 3
        roles = {i.role for i in instances}
        assert roles == {"attacker", "dc", "victim"}

    @patch("cms.experiments.orchestrator.engine_create_range")
    def test_ad_attack_lab_dc_has_domain_config(self, mock_engine: object) -> None:
        """AD Attack Lab DC instance has dc_config with domain settings."""
        agent = self._create_agent(self.windows_os)
        exp, run = self._create_provisioning_run(scenario_id="ad_attack_lab", agent=agent)

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        request_spec = mock_engine.call_args[0][0]
        range_spec = request_spec.items[0]
        dc = next(i for i in range_spec.all_instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name == "internal.shifter"
