"""Tests for experiment event publishing.

Tests the event publishing bridge that connects range provisioning
to experiment execution. Verifies exception handling, configuration edge
cases, and error chaining.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from cms.experiments.events import (
    ExperimentEventError,
    publish_experiment_event,
    publish_range_provisioned_for_experiment,
)
from shared.cloud.exceptions import CloudQueueError


class TestPublishExperimentEvent:
    """Tests for publish_experiment_event function."""

    @patch("cms.experiments.events.settings")
    @patch("cms.experiments.events.get_queue_publisher")
    def test_publishes_successfully(self, mock_get_publisher: MagicMock, mock_settings: MagicMock) -> None:
        """Successfully publishes event to configured CMS queue."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}}
        mock_publisher = MagicMock()
        mock_get_publisher.return_value = mock_publisher

        publish_experiment_event(
            event_type="experiment.run.range_provisioned",
            payload={"experiment_id": 1, "run_id": 1},
        )

        mock_publisher.send_message.assert_called_once()
        call_args = mock_publisher.send_message.call_args
        assert call_args[0][0] == "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"

    @patch("cms.experiments.events.settings")
    def test_raises_when_not_configured(self, mock_settings: MagicMock) -> None:
        """Raises ExperimentEventError when SQS queue is not configured."""
        mock_settings.SQS_QUEUE_CONFIG = {}

        with pytest.raises(ExperimentEventError, match="SQS_CMS_URL not configured"):
            publish_experiment_event(
                event_type="test.event",
                payload={"data": "value"},
            )

    @patch("cms.experiments.events.settings")
    def test_raises_when_url_empty(self, mock_settings: MagicMock) -> None:
        """Raises ExperimentEventError when queue URL is empty string."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": ""}}

        with pytest.raises(ExperimentEventError, match="SQS_CMS_URL not configured"):
            publish_experiment_event(
                event_type="test.event",
                payload={"data": "value"},
            )

    @patch("cms.experiments.events.settings")
    @patch("cms.experiments.events.get_queue_publisher")
    def test_raises_on_cloud_queue_failure(self, mock_get_publisher: MagicMock, mock_settings: MagicMock) -> None:
        """Raises ExperimentEventError when publisher raises CloudQueueError."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}}
        mock_publisher = MagicMock()
        mock_get_publisher.return_value = mock_publisher

        cloud_error = CloudQueueError("Service unavailable")
        mock_publisher.send_message.side_effect = cloud_error

        with pytest.raises(ExperimentEventError) as exc_info:
            publish_experiment_event(
                event_type="experiment.run.range_provisioned",
                payload={"experiment_id": 1, "run_id": 1},
            )

        assert "experiment.run.range_provisioned" in str(exc_info.value)
        assert exc_info.value.__cause__ is cloud_error

    @patch("cms.experiments.events.settings")
    @patch("cms.experiments.events.get_queue_publisher")
    def test_exception_message_includes_event_type(
        self, mock_get_publisher: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Exception message includes the event type for debugging."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}}
        mock_publisher = MagicMock()
        mock_get_publisher.return_value = mock_publisher
        mock_publisher.send_message.side_effect = CloudQueueError("Network error")

        with pytest.raises(ExperimentEventError) as exc_info:
            publish_experiment_event(
                event_type="experiment.run.custom_event",
                payload={"data": "test"},
            )

        assert "experiment.run.custom_event" in str(exc_info.value)


class TestPublishRangeProvisioned:
    """Tests for publish_range_provisioned_for_experiment wrapper function."""

    @patch("cms.experiments.events.settings")
    @patch("cms.experiments.events.get_queue_publisher")
    def test_publishes_with_correct_payload(self, mock_get_publisher: MagicMock, mock_settings: MagicMock) -> None:
        """Publishes range_provisioned event with correct structure."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}}
        mock_publisher = MagicMock()
        mock_get_publisher.return_value = mock_publisher

        provisioned_instances = {
            "Workstation": {"instance_id": "i-abc123"},
            "Server": {"instance_id": "i-def456"},
        }

        publish_range_provisioned_for_experiment(
            experiment_id=42,
            run_id=7,
            provisioned_instances=provisioned_instances,
        )

        mock_publisher.send_message.assert_called_once()
        call_args = mock_publisher.send_message.call_args
        message_body = json.loads(call_args[0][1])

        assert message_body["event_type"] == "experiment.run.range_provisioned"
        assert message_body["experiment_id"] == 42
        assert message_body["run_id"] == 7
        assert message_body["provisioned_instances"] == provisioned_instances

    @patch("cms.experiments.events.settings")
    @patch("cms.experiments.events.get_queue_publisher")
    def test_raises_on_publish_failure(self, mock_get_publisher: MagicMock, mock_settings: MagicMock) -> None:
        """Propagates ExperimentEventError from publish_experiment_event."""
        mock_settings.SQS_QUEUE_CONFIG = {"cms": {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}}
        mock_publisher = MagicMock()
        mock_get_publisher.return_value = mock_publisher
        mock_publisher.send_message.side_effect = CloudQueueError("Queue failure")

        with pytest.raises(ExperimentEventError):
            publish_range_provisioned_for_experiment(
                experiment_id=1,
                run_id=1,
                provisioned_instances={},
            )
