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

from unittest.mock import MagicMock, patch
from uuid import uuid4

from cms.experiments.schemas import RunStatus
from shared.enums import ResourceStatus

# notify_experiment_on_range_ready does a local import:
#   from cms.experiments.models import ExperimentRun
# We patch at the source module so the local import picks up the mock.
PATCH_EXP_RUN = "cms.experiments.models.ExperimentRun"


class TestRangeToExperimentBridge:
    """Tests for notify_experiment_on_range_ready bridge function."""

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    @patch(PATCH_EXP_RUN)
    def test_publishes_event_when_range_ready_for_experiment(self, mock_run_model, mock_publish):
        """When range status becomes READY and linked to experiment, publishes event."""
        mock_publish.return_value = True
        request_id = uuid4()

        # Mock the range instance
        ri = MagicMock()
        ri.request.request_id = request_id

        # Mock ExperimentRun.objects.select_related().get() to return a matching run
        mock_run = MagicMock()
        mock_run.experiment_id = 10
        mock_run.pk = 5
        mock_run_model.objects.select_related.return_value.get.return_value = mock_run
        mock_run_model.DoesNotExist = Exception

        from cms.handlers import notify_experiment_on_range_ready

        provisioned_instances = {"Workstation": {"instance_id": "i-abc123"}}
        notify_experiment_on_range_ready(ri, provisioned_instances)

        mock_publish.assert_called_once_with(
            experiment_id=10,
            run_id=5,
            provisioned_instances=provisioned_instances,
        )

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    @patch(PATCH_EXP_RUN)
    def test_does_nothing_for_range_without_experiment(self, mock_run_model, mock_publish):
        """Range not linked to any experiment run -> no event published."""
        request_id = uuid4()

        ri = MagicMock()
        ri.request.request_id = request_id

        # ExperimentRun not found
        mock_run_model.DoesNotExist = Exception
        mock_run_model.objects.select_related.return_value.get.side_effect = mock_run_model.DoesNotExist

        from cms.handlers import notify_experiment_on_range_ready

        notify_experiment_on_range_ready(ri, {})

        mock_publish.assert_not_called()

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    @patch(PATCH_EXP_RUN)
    def test_handles_deleted_request_gracefully(self, mock_run_model, mock_publish):
        """If range_instance has no request, no crash."""
        ri = MagicMock()
        ri.request = None

        from cms.handlers import notify_experiment_on_range_ready

        # Should not raise
        notify_experiment_on_range_ready(ri, {})
        mock_publish.assert_not_called()


class TestCmsHandlerBridgeIntegration:
    """Tests for process_range_event calling the bridge on READY status."""

    @patch("cms.handlers.notify_experiment_on_range_ready")
    @patch("cms.handlers._notify_ctf_range_status")
    @patch("cms.handlers.RangeInstance")
    def test_process_range_event_calls_bridge_on_ready(self, mock_ri_model, mock_ctf, mock_bridge):
        """process_range_event calls bridge when status transitions to READY."""
        request_id = str(uuid4())

        mock_instance = MagicMock()
        mock_instance.user_id = 1
        mock_instance.status = "provisioning"
        mock_instance.range_id = None
        mock_instance.pk = 99
        mock_ri_model.objects.get.return_value = mock_instance
        mock_ri_model.DoesNotExist = Exception

        event = {
            "event_type": "range.status.updated",
            "request_id": request_id,
            "range_id": 1,
            "user_id": 1,
            "new_status": ResourceStatus.READY.value,
        }

        from cms.handlers import process_range_event

        process_range_event(event)

        mock_bridge.assert_called_once()

    @patch("cms.handlers.notify_experiment_on_range_ready")
    @patch("cms.handlers._notify_ctf_range_status")
    @patch("cms.handlers.RangeInstance")
    def test_process_range_event_no_bridge_on_non_ready(self, mock_ri_model, mock_ctf, mock_bridge):
        """Bridge is NOT called for non-READY status transitions."""
        request_id = str(uuid4())

        mock_instance = MagicMock()
        mock_instance.user_id = 1
        mock_instance.status = "provisioning"
        mock_instance.range_id = None
        mock_instance.pk = 99
        mock_ri_model.objects.get.return_value = mock_instance
        mock_ri_model.DoesNotExist = Exception

        event = {
            "event_type": "range.status.updated",
            "request_id": request_id,
            "range_id": 1,
            "user_id": 1,
            "new_status": ResourceStatus.PROVISIONING.value,
        }

        from cms.handlers import process_range_event

        process_range_event(event)

        mock_bridge.assert_not_called()

    @patch("cms.handlers.publish_range_provisioned_for_experiment")
    @patch(PATCH_EXP_RUN)
    def test_bridge_marks_run_failed_on_sqs_error(self, mock_run_model, mock_publish):
        """When SQS publish fails, the experiment run is marked FAILED."""
        from cms.experiments.events import ExperimentEventError

        request_id = uuid4()
        ri = MagicMock()
        ri.request.request_id = request_id

        mock_run = MagicMock()
        mock_run.experiment_id = 10
        mock_run.pk = 5
        mock_run_model.objects.select_related.return_value.get.return_value = mock_run
        mock_run_model.DoesNotExist = Exception

        mock_publish.side_effect = ExperimentEventError("SQS unavailable")

        from cms.handlers import notify_experiment_on_range_ready

        provisioned_instances = {"Workstation": {"instance_id": "i-abc123"}}
        notify_experiment_on_range_ready(ri, provisioned_instances)

        # Run should be marked FAILED with error message
        assert mock_run.error_message == "Failed to publish range provisioning notification"
        mock_run.save.assert_called_once()
        mock_run.transition_to.assert_called_once_with(RunStatus.FAILED)
