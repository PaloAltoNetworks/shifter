"""Tests for the range-to-experiment event bridge.

When a range's status transitions to READY and that range is linked to
an experiment run, the CMS handler should publish an experiment event
to trigger the next phase (script execution).

Logic under test:
- Detects when a provisioned range is linked to an experiment run
- Publishes experiment.run.range_provisioned event with correct context
- Does nothing when range is not linked to an experiment
- Does nothing for non-READY status transitions
- Handles missing experiment run gracefully
"""

from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.schemas import ExperimentStatus, RunStatus
from cms.models import AgentConfig, OperatingSystem, RangeInstance, Request
from shared.enums import RequestType, ResourceStatus

User = get_user_model()

TEST_PASSWORD = "test"  # nosec B105


class RangeToExperimentBridgeTest(TestCase):
    """Tests for notify_experiment_on_range_ready bridge function."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="bridge_user", password=TEST_PASSWORD, is_staff=True)
        cls.windows_os = OperatingSystem.objects.get(slug="windows")
        cls.agent = AgentConfig.objects.create(
            user=cls.user,
            name="Bridge Agent",
            os=cls.windows_os,
            s3_key="agents/test/bridge.msi",
            original_filename="bridge.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123",
        )

    def _create_experiment_with_range(self) -> tuple[Experiment, ExperimentRun, RangeInstance]:
        """Create an experiment, run, request, and range instance."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Bridge Test",
            scenario_id="basic",
            agent=self.agent,
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        request_id = uuid4()
        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.PROVISIONING.value,
            request_id=request_id,
        )
        cms_request = Request.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=self.user,
        )
        ri = RangeInstance.objects.create(
            request=cms_request,
            scenario_id="basic",
            user_id=self.user.pk,
            agent=self.agent,
            range_spec={"scenario_id": "basic"},
        )
        return exp, run, ri

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_publishes_event_when_range_ready_for_experiment(self, mock_publish: object) -> None:
        """When range status becomes READY and linked to experiment, publishes event."""
        mock_publish.return_value = True
        exp, run, ri = self._create_experiment_with_range()

        from cms.handlers import notify_experiment_on_range_ready

        provisioned_instances = {"Workstation": {"instance_id": "i-abc123"}}
        notify_experiment_on_range_ready(ri, provisioned_instances)

        mock_publish.assert_called_once_with(
            experiment_id=exp.pk,
            run_id=run.pk,
            provisioned_instances=provisioned_instances,
        )

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_does_nothing_for_range_without_experiment(self, mock_publish: object) -> None:
        """Range not linked to any experiment run → no event published."""
        request_id = uuid4()
        cms_request = Request.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=self.user,
        )
        ri = RangeInstance.objects.create(
            request=cms_request,
            scenario_id="basic",
            user_id=self.user.pk,
            range_spec={"scenario_id": "basic"},
        )

        from cms.handlers import notify_experiment_on_range_ready

        notify_experiment_on_range_ready(ri, {})

        mock_publish.assert_not_called()

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_handles_deleted_request_gracefully(self, mock_publish: object) -> None:
        """If request has no linked experiment run, no crash."""
        request_id = uuid4()
        cms_request = Request.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=self.user,
        )
        ri = RangeInstance.objects.create(
            request=cms_request,
            scenario_id="basic",
            user_id=self.user.pk,
            range_spec={"scenario_id": "basic"},
        )

        from cms.handlers import notify_experiment_on_range_ready

        # Should not raise
        notify_experiment_on_range_ready(ri, {})
        mock_publish.assert_not_called()


class CmsHandlerBridgeIntegrationTest(TestCase):
    """Tests for process_range_event calling the bridge on READY status."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="handler_bridge_user", password=TEST_PASSWORD, is_staff=True)
        cls.windows_os = OperatingSystem.objects.get(slug="windows")
        cls.agent = AgentConfig.objects.create(
            user=cls.user,
            name="Handler Bridge Agent",
            os=cls.windows_os,
            s3_key="agents/test/handler_bridge.msi",
            original_filename="handler_bridge.msi",
            file_size_bytes=5_000_000,
            sha256_hash="abc123",
        )

    def _create_experiment_with_range(self) -> tuple[Experiment, ExperimentRun, RangeInstance]:
        """Create an experiment, run, request, and range instance."""
        exp = Experiment.objects.create(
            user=self.user,
            name="Handler Bridge Test",
            scenario_id="basic",
            agent=self.agent,
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        request_id = uuid4()
        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.PROVISIONING.value,
            request_id=request_id,
        )
        cms_request = Request.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=self.user,
        )
        ri = RangeInstance.objects.create(
            request=cms_request,
            scenario_id="basic",
            user_id=self.user.pk,
            agent=self.agent,
            range_spec={"scenario_id": "basic"},
            status=ResourceStatus.PROVISIONING.value,
        )
        return exp, run, ri

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_process_range_event_calls_bridge_on_ready(self, mock_publish: object) -> None:
        """process_range_event calls bridge when status transitions to READY."""
        mock_publish.return_value = True
        exp, run, _ri = self._create_experiment_with_range()

        event = {
            "event_type": "range.status.updated",
            "request_id": str(run.request_id),
            "range_id": 1,
            "user_id": self.user.pk,
            "new_status": ResourceStatus.READY.value,
        }

        from cms.handlers import process_range_event

        process_range_event(event)

        # The bridge should have been called
        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args[1]
        assert call_kwargs["experiment_id"] == exp.pk
        assert call_kwargs["run_id"] == run.pk

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_process_range_event_no_bridge_on_non_ready(self, mock_publish: object) -> None:
        """Bridge is NOT called for non-READY status transitions."""
        _exp, run, _ri = self._create_experiment_with_range()

        event = {
            "event_type": "range.status.updated",
            "request_id": str(run.request_id),
            "range_id": 1,
            "user_id": self.user.pk,
            "new_status": ResourceStatus.PROVISIONING.value,
        }

        from cms.handlers import process_range_event

        process_range_event(event)

        mock_publish.assert_not_called()

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_bridge_marks_run_failed_on_sqs_error(self, mock_publish: object) -> None:
        """When SQS publish fails, the experiment run is marked FAILED."""
        from cms.experiments.events import ExperimentEventError

        _exp, run, ri = self._create_experiment_with_range()

        # Simulate SQS publish failure
        mock_publish.side_effect = ExperimentEventError("SQS unavailable")

        from cms.handlers import notify_experiment_on_range_ready

        provisioned_instances = {"Workstation": {"instance_id": "i-abc123"}}
        notify_experiment_on_range_ready(ri, provisioned_instances)

        # Run should be marked FAILED with error message
        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "Failed to publish range provisioning notification" in run.error_message

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    def test_bridge_integration_with_sqs_failure(self, mock_publish: object) -> None:
        """Full integration test: range becomes READY but SQS fails."""
        from cms.experiments.events import ExperimentEventError

        _exp, run, _ri = self._create_experiment_with_range()

        # Simulate SQS failure
        mock_publish.side_effect = ExperimentEventError("Queue not found")

        event = {
            "event_type": "range.status.updated",
            "request_id": str(run.request_id),
            "range_id": 1,
            "user_id": self.user.pk,
            "new_status": ResourceStatus.READY.value,
            "instances": {"Workstation": {"instance_id": "i-abc123"}},
        }

        from cms.handlers import process_range_event

        # Should not raise — handler catches exception and marks run FAILED
        process_range_event(event)

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert "Failed to publish range provisioning notification" in run.error_message
