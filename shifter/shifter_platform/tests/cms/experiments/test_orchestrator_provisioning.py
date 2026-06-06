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

from unittest.mock import MagicMock, patch
from uuid import UUID

from cms.experiments.schemas import ExperimentStatus, RunStatus


def _make_mock_run(run_pk=1, status=RunStatus.PROVISIONING.value):
    """Create a mock ExperimentRun."""
    run = MagicMock()
    run.pk = run_pk
    run.run_number = 1
    run.status = status
    run.request_id = None
    run.error_message = ""
    run.metadata = None
    return run


def _make_mock_agent(deleted=False, os_slug="windows"):
    """Create a mock AgentConfig."""
    agent = MagicMock()
    agent.pk = 10
    agent.name = "Test Agent"
    agent.s3_key = "agents/1/test_agent.msi"
    agent.original_filename = "test_agent.msi"
    agent.file_size_bytes = 5_000_000
    agent.sha256_hash = "abc123def456"
    agent.os.slug = os_slug
    if deleted:
        from django.utils import timezone

        agent.deleted_at = timezone.now()
    else:
        agent.deleted_at = None
    return agent


def _make_mock_experiment(exp_pk=1, user_pk=1, scenario_id="basic", agent=None):
    """Create a mock Experiment with user and agent."""
    exp = MagicMock()
    exp.pk = exp_pk
    exp.scenario_id = scenario_id
    exp.user.pk = user_pk
    exp.agent = agent
    exp.status = ExperimentStatus.RUNNING.value
    exp.total_runs = 1
    exp.max_parallel_runs = 1
    return exp


# The _request_range_provisioning method uses local imports:
#   from cms.models import AgentConfig, RangeInstance, Request
#   from cms.scenarios.hydrator import hydrate_scenario
#   from shared.schemas import RequestSpec
# We patch at the source module level since local imports re-read from sys.modules.
PATCH_ENGINE = "cms.experiments.orchestrator.engine_create_range"
PATCH_HYDRATE = "cms.scenarios.hydrator.hydrate_scenario"
PATCH_REQUEST = "cms.models.Request"
PATCH_RANGE_INSTANCE = "cms.models.RangeInstance"
PATCH_EXPERIMENT = "cms.experiments.orchestrator.Experiment"
PATCH_REQUEST_SPEC = "shared.schemas.RequestSpec"


class TestRequestRangeProvisioningRecords:
    """Record creation and engine call tests for range provisioning."""

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_creates_cms_request_record(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Provisioning creates a CMS Request for engine correlation."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_request_model.objects.create.assert_called_once()
        assert run.request_id is not None

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_stores_request_id_on_run(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Provisioning stores request_id on ExperimentRun for correlation."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        assert run.request_id is not None
        assert isinstance(run.request_id, UUID)

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_creates_range_instance_record(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Provisioning creates a RangeInstance for CMS tracking."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_ri_model.objects.create.assert_called_once()
        call_kwargs = mock_ri_model.objects.create.call_args[1]
        assert call_kwargs["scenario_id"] == "basic"
        assert call_kwargs["user_id"] == 1
        assert call_kwargs["agent"] == agent

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_calls_engine_create_range(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Provisioning calls engine.create_range."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        assert isinstance(run.request_id, UUID)
        mock_req_spec.assert_called_once_with(request_id=run.request_id, user_id=exp.user.pk, items=[mock_range_spec])
        mock_engine.assert_called_once_with(mock_req_spec.return_value)

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_range_spec_has_correct_scenario_id(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """The scenario_id passed to hydrate_scenario matches the experiment."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent, scenario_id="basic")
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.scenario_id = "basic"
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_hydrate.assert_called_once()
        assert mock_hydrate.call_args[0][0] == "basic"

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_provisions_scenario_without_agent(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Scenarios that don't require agents can be provisioned without one."""
        exp = _make_mock_experiment(agent=None, scenario_id="basic")
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_engine.assert_called_once()
        assert run.request_id is not None


class TestRequestRangeProvisioningFailures:
    """Failure tests for range provisioning."""

    @patch(PATCH_ENGINE)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_invalid_scenario_fails_run(self, mock_exp_model, mock_hydrate, mock_engine):
        """Invalid scenario_id transitions run to FAILED with error message."""
        exp = _make_mock_experiment(agent=None, scenario_id="nonexistent")
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_hydrate.side_effect = ValueError("Scenario 'nonexistent' not found")

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        assert "nonexistent" in run.error_message.lower() or "not found" in run.error_message.lower()
        run.transition_to.assert_called_once_with(RunStatus.FAILED)
        mock_engine.assert_not_called()

    @patch(PATCH_ENGINE)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_missing_required_agent_fails_run(self, mock_exp_model, mock_hydrate, mock_engine):
        """Scenario requiring agent but experiment has none -> run FAILED."""
        from cms.exceptions import CMSError

        exp = _make_mock_experiment(agent=None, scenario_id="basic")
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_hydrate.side_effect = CMSError("Agent required for scenario 'basic'")

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        assert run.error_message != ""
        run.transition_to.assert_called_once_with(RunStatus.FAILED)
        mock_engine.assert_not_called()

    @patch(PATCH_ENGINE, side_effect=Exception("ECS down"))
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_engine_failure_fails_run(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """Engine failure transitions run to FAILED with error details."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        assert "ECS down" in run.error_message
        run.transition_to.assert_called_once_with(RunStatus.FAILED)

    @patch(PATCH_ENGINE)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_deleted_agent_fails_run(self, mock_exp_model, mock_hydrate, mock_engine):
        """Soft-deleted agent fails the run."""
        agent = _make_mock_agent(deleted=True)
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        run.transition_to.assert_called_once_with(RunStatus.FAILED)
        mock_engine.assert_not_called()


class TestRequestRangeProvisioningScenarioData:
    """Scenario-specific payload tests for range provisioning."""

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_ad_attack_lab_calls_hydrate_with_correct_scenario(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """AD Attack Lab passes 'ad_attack_lab' scenario_id to hydrate."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent, scenario_id="ad_attack_lab")
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "ad_attack_lab"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        mock_hydrate.assert_called_once()
        assert mock_hydrate.call_args[0][0] == "ad_attack_lab"
        mock_engine.assert_called_once()

    @patch(PATCH_ENGINE)
    @patch(PATCH_RANGE_INSTANCE)
    @patch(PATCH_REQUEST)
    @patch(PATCH_REQUEST_SPEC)
    @patch(PATCH_HYDRATE)
    @patch(PATCH_EXPERIMENT)
    def test_range_instance_stores_range_spec_json(
        self, mock_exp_model, mock_hydrate, mock_req_spec, mock_request_model, mock_ri_model, mock_engine
    ):
        """RangeInstance.range_spec stores the hydrated spec as JSON."""
        agent = _make_mock_agent()
        exp = _make_mock_experiment(agent=agent)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = exp

        mock_range_spec = MagicMock()
        mock_range_spec.model_dump.return_value = {"scenario_id": "basic"}
        mock_hydrate.return_value = mock_range_spec

        run = _make_mock_run()

        from cms.experiments.orchestrator import ExperimentOrchestrator

        orch = ExperimentOrchestrator(exp.pk)
        orch._request_range_provisioning(run)

        call_kwargs = mock_ri_model.objects.create.call_args[1]
        assert call_kwargs["range_spec"] == {"scenario_id": "basic"}
