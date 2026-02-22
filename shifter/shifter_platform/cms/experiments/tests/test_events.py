"""Tests for experiment event publishing.

Tests the SQS event publishing bridge that connects range provisioning
to experiment execution. Verifies exception handling, configuration edge
cases, and error chaining.
"""

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.test import TestCase, override_settings

from cms.experiments.events import (
    ExperimentEventError,
    publish_experiment_event,
    publish_range_provisioned_for_experiment,
)


class PublishExperimentEventTest(TestCase):
    """Tests for publish_experiment_event function."""

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="us-east-2",
    )
    @patch("cms.experiments.events.boto3.client")
    def test_publishes_successfully(self, mock_boto_client: MagicMock) -> None:
        """Successfully publishes event to configured SQS queue."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs

        # Should not raise
        publish_experiment_event(
            event_type="experiment.run.range_provisioned",
            payload={"experiment_id": 1, "run_id": 1},
        )

        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == "https://sqs.us-east-2.amazonaws.com/123/experiments"

    @override_settings(
        SQS_QUEUE_CONFIG={},
        AWS_REGION="us-east-2",
    )
    def test_returns_gracefully_when_not_configured(self) -> None:
        """Returns without error when SQS queue is not configured."""
        # Should not raise — graceful return for unconfigured queue
        publish_experiment_event(
            event_type="test.event",
            payload={"data": "value"},
        )

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": ""}},
        AWS_REGION="us-east-2",
    )
    def test_returns_gracefully_when_url_empty(self) -> None:
        """Returns without error when queue URL is empty string."""
        # Should not raise — graceful return for empty URL
        publish_experiment_event(
            event_type="test.event",
            payload={"data": "value"},
        )

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="us-east-2",
    )
    @patch("cms.experiments.events.boto3.client")
    def test_raises_on_sqs_failure(self, mock_boto_client: MagicMock) -> None:
        """Raises ExperimentEventError when SQS send_message fails."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs

        # Simulate SQS failure
        sqs_error = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "Service unavailable"}},
            "SendMessage",
        )
        mock_sqs.send_message.side_effect = sqs_error

        with self.assertRaises(ExperimentEventError) as ctx:
            publish_experiment_event(
                event_type="experiment.run.range_provisioned",
                payload={"experiment_id": 1, "run_id": 1},
            )

        # Verify exception message includes context
        assert "experiment.run.range_provisioned" in str(ctx.exception)
        # Verify exception chaining
        assert ctx.exception.__cause__ is sqs_error

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="",
    )
    def test_raises_on_missing_region(self) -> None:
        """Raises ExperimentEventError when AWS_REGION is not configured."""
        with self.assertRaises(ExperimentEventError) as ctx:
            publish_experiment_event(
                event_type="test.event",
                payload={"data": "value"},
            )

        # Verify the root cause was ValueError about AWS_REGION
        assert ctx.exception.__cause__ is not None
        assert "AWS_REGION" in str(ctx.exception.__cause__)

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="us-east-2",
    )
    @patch("cms.experiments.events.boto3.client")
    def test_exception_message_includes_event_type(self, mock_boto_client: MagicMock) -> None:
        """Exception message includes the event type for debugging."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = Exception("Network error")

        with self.assertRaises(ExperimentEventError) as ctx:
            publish_experiment_event(
                event_type="experiment.run.custom_event",
                payload={"data": "test"},
            )

        # Event type should be in the exception message
        assert "experiment.run.custom_event" in str(ctx.exception)


class PublishRangeProvisionedTest(TestCase):
    """Tests for publish_range_provisioned_for_experiment wrapper function."""

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="us-east-2",
    )
    @patch("cms.experiments.events.boto3.client")
    def test_publishes_with_correct_payload(self, mock_boto_client: MagicMock) -> None:
        """Publishes range_provisioned event with correct structure."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs

        provisioned_instances = {
            "Workstation": {"instance_id": "i-abc123"},
            "Server": {"instance_id": "i-def456"},
        }

        publish_range_provisioned_for_experiment(
            experiment_id=42,
            run_id=7,
            provisioned_instances=provisioned_instances,
        )

        mock_sqs.send_message.assert_called_once()
        # Verify the message body structure
        import json

        call_kwargs = mock_sqs.send_message.call_args[1]
        message_body = json.loads(call_kwargs["MessageBody"])

        assert message_body["event_type"] == "experiment.run.range_provisioned"
        assert message_body["experiment_id"] == 42
        assert message_body["run_id"] == 7
        assert message_body["provisioned_instances"] == provisioned_instances

    @override_settings(
        SQS_QUEUE_CONFIG={"experiments": {"url": "https://sqs.us-east-2.amazonaws.com/123/experiments"}},
        AWS_REGION="us-east-2",
    )
    @patch("cms.experiments.events.boto3.client")
    def test_raises_on_sqs_failure(self, mock_boto_client: MagicMock) -> None:
        """Propagates ExperimentEventError from publish_experiment_event."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = Exception("SQS failure")

        with self.assertRaises(ExperimentEventError):
            publish_range_provisioned_for_experiment(
                experiment_id=1,
                run_id=1,
                provisioned_instances={},
            )
