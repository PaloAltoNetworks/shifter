"""Tests for SQS event handler dispatch."""

import json
from unittest.mock import MagicMock, patch

from cms.experiments.handlers import parse_sns_message, process_event
from cms.experiments.schemas import RunStatus


class TestParseMessage:
    def test_direct_dict(self):
        result = parse_sns_message({"event_type": "test"})
        assert result["event_type"] == "test"

    def test_json_string(self):
        result = parse_sns_message('{"event_type": "test"}')
        assert result["event_type"] == "test"

    def test_sns_envelope(self):
        envelope = {"Message": json.dumps({"event_type": "test"})}
        result = parse_sns_message(envelope)
        assert result["event_type"] == "test"


class TestProcessEvent:
    @patch("cms.experiments.handlers.ExperimentOrchestrator")
    def test_ignores_unknown_event(self, mock_orch_cls):
        """Unknown event_type → no orchestrator constructed, no handler dispatched."""
        process_event({"event_type": "unknown.event", "event_id": "123"})
        mock_orch_cls.assert_not_called()

    @patch("cms.experiments.handlers.ExperimentOrchestrator")
    def test_experiment_start_schedules_runs(self, mock_orch_cls):
        """experiment.start event creates orchestrator and calls schedule_runs."""
        mock_orch = MagicMock()
        mock_orch_cls.return_value = mock_orch

        process_event(
            {
                "event_type": "experiment.start",
                "experiment_id": 42,
            }
        )

        mock_orch_cls.assert_called_once_with(42)
        mock_orch.schedule_runs.assert_called_once()

    @patch("cms.experiments.handlers.Experiment")
    @patch("cms.experiments.handlers.ExperimentRun")
    @patch("cms.experiments.handlers.ExperimentOrchestrator")
    def test_run_failed_event(self, mock_orch_cls, mock_run_model, mock_exp_model):
        """experiment.run.failed event calls handle_run_failed on orchestrator."""
        mock_orch = MagicMock()
        mock_orch_cls.return_value = mock_orch

        # Mock the ExperimentRun.objects.get for broadcast (lookup at handler module level).
        mock_run = MagicMock(run_number=1, status=RunStatus.FAILED.value)
        mock_run_model.objects.get.return_value = mock_run
        mock_run_model.DoesNotExist = Exception

        # Mock Experiment.objects.get for broadcast (lookup at handler module level).
        mock_exp = MagicMock(status="failed")
        mock_exp_model.objects.get.return_value = mock_exp
        mock_exp_model.DoesNotExist = Exception

        process_event(
            {
                "event_type": "experiment.run.failed",
                "experiment_id": 10,
                "run_id": 5,
                "error_message": "SSM timeout",
            }
        )

        mock_orch_cls.assert_called_once_with(10)
        mock_orch.handle_run_failed.assert_called_once_with(5, "SSM timeout")

    @patch("cms.experiments.handlers.ExperimentOrchestrator")
    def test_string_experiment_id_ignored(self, mock_orch_cls):
        """String experiment_id fails int validation → orchestrator never built."""
        process_event(
            {
                "event_type": "experiment.start",
                "experiment_id": "not-an-int",
            }
        )
        mock_orch_cls.assert_not_called()

    @patch("cms.experiments.handlers.ExperimentOrchestrator")
    def test_string_run_id_ignored(self, mock_orch_cls):
        """String run_id should be silently ignored (not crash)."""
        process_event(
            {
                "event_type": "experiment.run.failed",
                "experiment_id": 10,
                "run_id": "not-an-int",
            }
        )
        # No exception raised -- event was silently dropped
        mock_orch_cls.assert_not_called()
