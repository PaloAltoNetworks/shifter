"""Tests for shared cloud EventBus adapters and get_event_bus() factory.

Mocks only the boto3/pubsub boundary (ADR-019).  Drives the real adapter
classes through their public publish() method.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from shared.cloud.aws.event_bus import AWSEventBus
from shared.cloud.exceptions import CloudEventBusError


class TestAWSEventBusPublish:
    """AWSEventBus publishes to SNS via boto3."""

    def test_publish_success_calls_sns(self):
        bus = AWSEventBus()
        fake_client = MagicMock()

        with patch("boto3.client", return_value=fake_client):
            bus.publish(
                "arn:aws:sns:us-east-2:123456789012:range-events",
                "hello",
                attributes={"event_type": "range.ready"},
            )

        fake_client.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:us-east-2:123456789012:range-events",
            Message="hello",
            MessageAttributes={"event_type": {"DataType": "String", "StringValue": "range.ready"}},
        )

    def test_publish_no_attributes_omits_message_attributes(self):
        bus = AWSEventBus()
        fake_client = MagicMock()

        with patch("boto3.client", return_value=fake_client):
            bus.publish("arn:aws:sns:us-east-2:123456789012:range-events", "hello")

        call_kwargs = fake_client.publish.call_args[1]
        assert "MessageAttributes" not in call_kwargs

    def test_client_error_raises_cloud_event_bus_error(self):
        bus = AWSEventBus()
        fake_client = MagicMock()
        fake_client.publish.side_effect = ClientError(
            {"Error": {"Code": "NotFound", "Message": "Topic not found"}},
            "Publish",
        )

        with (
            patch("boto3.client", return_value=fake_client),
            pytest.raises(CloudEventBusError),
        ):
            bus.publish("arn:aws:sns:us-east-2:123456789012:range-events", "hello")

    def test_botocore_error_raises_cloud_event_bus_error(self):
        bus = AWSEventBus()
        fake_client = MagicMock()
        fake_client.publish.side_effect = BotoCoreError()

        with (
            patch("boto3.client", return_value=fake_client),
            pytest.raises(CloudEventBusError),
        ):
            bus.publish("arn:aws:sns:us-east-2:123456789012:range-events", "hello")

    def test_multiple_attributes_are_all_converted(self):
        bus = AWSEventBus()
        fake_client = MagicMock()

        with patch("boto3.client", return_value=fake_client):
            bus.publish(
                "arn:aws:sns:us-east-2:123456789012:range-events",
                "payload",
                attributes={"event_type": "range.ready", "source": "drainer"},
            )

        call_kwargs = fake_client.publish.call_args[1]
        attrs = call_kwargs["MessageAttributes"]
        assert attrs["event_type"] == {"DataType": "String", "StringValue": "range.ready"}
        assert attrs["source"] == {"DataType": "String", "StringValue": "drainer"}


class TestGCPEventBusPublish:
    """GCPEventBus publishes to Pub/Sub."""

    def _make_fake_pubsub(self, topic_path: str = "projects/proj/topics/test"):
        fake_pubsub = MagicMock()
        fake_client = MagicMock()
        fake_future = MagicMock()
        fake_pubsub.PublisherClient.return_value = fake_client
        fake_client.topic_path.return_value = topic_path
        fake_client.publish.return_value = fake_future
        return fake_pubsub, fake_client, fake_future

    def test_publish_success_calls_result(self, settings):
        from shared.cloud.gcp.event_bus import GCPEventBus

        settings.CLOUD_PROVIDER = "gcp"
        settings.GCP_PROJECT_ID = "proj"
        bus = GCPEventBus()
        fake_pubsub, _client, fake_future = self._make_fake_pubsub()

        with patch.dict("sys.modules", {"google.cloud.pubsub_v1": fake_pubsub}):
            bus.publish("test-topic", "hello", attributes={"event_type": "range.ready"})

        fake_future.result.assert_called_once()

    def test_publish_encodes_message_as_utf8(self, settings):
        from shared.cloud.gcp.event_bus import GCPEventBus

        settings.GCP_PROJECT_ID = "proj"
        bus = GCPEventBus()
        fake_pubsub, fake_client, _future = self._make_fake_pubsub()

        with patch.dict("sys.modules", {"google.cloud.pubsub_v1": fake_pubsub}):
            bus.publish("test-topic", "hello")

        call_args = fake_client.publish.call_args
        assert call_args[0][1] == b"hello"

    def test_pubsub_error_raises_cloud_event_bus_error(self, settings):
        from shared.cloud.gcp.event_bus import GCPEventBus

        settings.GCP_PROJECT_ID = "proj"
        bus = GCPEventBus()
        fake_pubsub = MagicMock()
        fake_client = MagicMock()
        fake_pubsub.PublisherClient.return_value = fake_client
        fake_client.topic_path.return_value = "projects/proj/topics/test"
        fake_client.publish.side_effect = RuntimeError("Pub/Sub failure")

        with (
            patch.dict("sys.modules", {"google.cloud.pubsub_v1": fake_pubsub}),
            pytest.raises(CloudEventBusError),
        ):
            bus.publish("test-topic", "hello")

    def test_import_error_raises_cloud_event_bus_error(self, settings):
        from shared.cloud.gcp.event_bus import GCPEventBus

        settings.GCP_PROJECT_ID = "proj"
        bus = GCPEventBus()

        with (
            patch.dict("sys.modules", {"google.cloud.pubsub_v1": None}),
            pytest.raises(CloudEventBusError),
        ):
            bus.publish("test-topic", "hello")


class TestGetEventBusFactory:
    """get_event_bus() returns the correct implementation by provider."""

    def test_aws_provider_returns_aws_event_bus(self, settings):
        from shared.cloud import get_event_bus
        from shared.cloud.aws.event_bus import AWSEventBus

        settings.CLOUD_PROVIDER = "aws"
        bus = get_event_bus()
        assert isinstance(bus, AWSEventBus)

    def test_gcp_provider_returns_gcp_event_bus(self, settings):
        from shared.cloud import get_event_bus
        from shared.cloud.gcp.event_bus import GCPEventBus

        settings.CLOUD_PROVIDER = "gcp"
        bus = get_event_bus()
        assert isinstance(bus, GCPEventBus)

    def test_unknown_provider_raises(self, settings):
        from shared.cloud import get_event_bus
        from shared.cloud.exceptions import CloudProviderNotImplementedError

        settings.CLOUD_PROVIDER = "azure"
        with pytest.raises(CloudProviderNotImplementedError):
            get_event_bus()

    def test_event_bus_satisfies_protocol(self, settings):
        from shared.cloud import get_event_bus
        from shared.cloud.types import EventBus

        settings.CLOUD_PROVIDER = "aws"
        bus = get_event_bus()
        assert isinstance(bus, EventBus)
