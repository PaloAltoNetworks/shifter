"""Tests for SNS event publishing in events.py.

This module tests the event publishing functions that send range status
events to SNS for fan-out.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


class TestGetSNSClient:
    """Tests for _get_sns_client() function."""

    def test_creates_sns_client_with_region_from_env(self, monkeypatch):
        """Client is created with AWS_REGION from environment."""
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

        from events import _get_sns_client

        with patch("events.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            _get_sns_client()

            mock_boto.assert_called_once_with("sns", region_name="us-west-2", endpoint_url=None)

    def test_uses_default_region_when_not_set(self, monkeypatch):
        """Client uses us-east-2 as default region."""
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

        from events import _get_sns_client

        with patch("events.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            _get_sns_client()

            mock_boto.assert_called_once_with("sns", region_name="us-east-2", endpoint_url=None)


class TestGetSNSTopicARN:
    """Tests for _get_sns_topic_arn() function."""

    def test_returns_arn_from_environment(self, monkeypatch):
        """Returns SNS_RANGE_EVENTS_ARN from environment."""
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

        from events import _get_sns_topic_arn

        assert _get_sns_topic_arn() == "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events"

    def test_raises_when_arn_not_set(self, monkeypatch):
        """Raises ValueError when SNS_RANGE_EVENTS_ARN not set."""
        monkeypatch.delenv("SNS_RANGE_EVENTS_ARN", raising=False)

        from events import _get_sns_topic_arn

        with pytest.raises(ValueError, match="SNS_RANGE_EVENTS_ARN"):
            _get_sns_topic_arn()


class TestPublishEvent:
    """Tests for _publish_event() internal function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_event_to_sns_topic(self, mock_sns_env):
        """Event is published to SNS with correct message and attributes."""
        from events import _publish_event

        with patch("events._get_sns_client") as mock_get_client:
            mock_sns = MagicMock()
            mock_get_client.return_value = mock_sns

            event = {
                "event_type": "range.status.updated",
                "range_id": 42,
                "user_id": 1,
                "new_status": "provisioning",
            }

            _publish_event(event)

            mock_sns.publish.assert_called_once()
            call_kwargs = mock_sns.publish.call_args.kwargs

            assert call_kwargs["TopicArn"] == "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events"
            assert json.loads(call_kwargs["Message"]) == event
            assert call_kwargs["MessageAttributes"]["event_type"]["StringValue"] == "range.status.updated"

    def test_includes_message_attributes(self, mock_sns_env):
        """Message attributes include event_type for filtering."""
        from events import _publish_event

        with patch("events._get_sns_client") as mock_get_client:
            mock_sns = MagicMock()
            mock_get_client.return_value = mock_sns

            event = {"event_type": "range.provisioned", "range_id": 42}

            _publish_event(event)

            call_kwargs = mock_sns.publish.call_args.kwargs
            attrs = call_kwargs["MessageAttributes"]

            assert attrs["event_type"]["DataType"] == "String"
            assert attrs["event_type"]["StringValue"] == "range.provisioned"

    def test_logs_debug_on_success(self, mock_sns_env, caplog):
        """Logs debug message on successful publish."""
        from events import _publish_event

        with (
            patch("events._get_sns_client") as mock_get_client,
            caplog.at_level(logging.DEBUG, logger="events"),
        ):
            mock_sns = MagicMock()
            mock_get_client.return_value = mock_sns

            _publish_event({"event_type": "range.status.updated", "range_id": 42})

            assert "Published" in caplog.text or "range_id=42" in caplog.text

    def test_logs_error_on_sns_failure(self, mock_sns_env, caplog):
        """Logs error when SNS publish fails."""
        from events import _publish_event

        with (
            patch("events._get_sns_client") as mock_get_client,
            caplog.at_level(logging.ERROR, logger="events"),
        ):
            mock_sns = MagicMock()
            mock_sns.publish.side_effect = Exception("SNS error")
            mock_get_client.return_value = mock_sns

            # Should not raise, but should log error
            _publish_event({"event_type": "range.status.updated", "range_id": 42})

            assert "error" in caplog.text.lower() or "fail" in caplog.text.lower()


class TestPublishStatusUpdate:
    """Tests for publish_status_update() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_status_change_event(self, mock_sns_env):
        """Publishes event with status transition details."""
        from events import publish_status_update

        with patch("events._publish_event") as mock_publish:
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="provisioning",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "range.status.updated"
            assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert event["range_id"] == 42
            assert event["user_id"] == 1
            assert event["new_status"] == "provisioning"

    def test_includes_error_message_when_provided(self, mock_sns_env):
        """Error message is included in event when provided."""
        from events import publish_status_update

        with patch("events._publish_event") as mock_publish:
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="failed",
                error_message="Subnet exhausted",
            )

            event = mock_publish.call_args[0][0]
            assert event["error_message"] == "Subnet exhausted"

    def test_logs_info_on_status_change(self, mock_sns_env, caplog):
        """Logs info message for status changes."""
        from events import publish_status_update

        with (
            patch("events._publish_event"),
            caplog.at_level(logging.INFO, logger="events"),
        ):
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="provisioning",
            )

            assert "42" in caplog.text
            assert "provisioning" in caplog.text


class TestPublishReady:
    """Tests for publish_ready() function.

    publish_ready() is notification-only. All state (instances, subnets) is
    written directly to the database by the provisioner before this event
    is published.
    """

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_status_update_and_provisioned_events(self, mock_sns_env):
        """Publishes both status update (ready) and provisioned events."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

            # Should publish both status update and provisioned event
            assert mock_publish.call_count == 2

            calls = [call[0][0] for call in mock_publish.call_args_list]
            event_types = [c.get("event_type") for c in calls]

            assert "range.status.updated" in event_types
            assert "range.provisioned" in event_types

    def test_provisioned_event_is_notification_only(self, mock_sns_env):
        """Provisioned event contains only identification fields, no state data."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

            # Find the provisioned event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            provisioned_events = [c for c in calls if c.get("event_type") == "range.provisioned"]

            assert len(provisioned_events) == 1
            event = provisioned_events[0]

            # Should have identification fields
            assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert event["range_id"] == 42
            assert event["user_id"] == 1
            assert "event_id" in event
            assert "timestamp" in event

            # Should NOT have state data (provisioner writes directly to DB)
            assert "instances" not in event
            assert "subnets" not in event
            assert "pulumi_stack" not in event

    def test_status_update_sets_ready_status(self, mock_sns_env):
        """Status update event has new_status='ready'."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

            # Find the status update event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            status_events = [c for c in calls if c.get("event_type") == "range.status.updated"]

            assert len(status_events) == 1
            assert status_events[0]["new_status"] == "ready"


class TestPublishFailed:
    """Tests for publish_failed() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_failed_status_with_error(self, mock_sns_env):
        """Publishes status update with failed status and error message."""
        from events import publish_failed

        with patch("events._publish_event") as mock_publish:
            publish_failed(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                error_message="Instance launch failed",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["new_status"] == "failed"
            assert event["error_message"] == "Instance launch failed"


class TestPublishDestroyed:
    """Tests for publish_destroyed() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_destroyed_event(self, mock_sns_env):
        """Publishes range.destroyed event."""
        from events import publish_destroyed

        with patch("events._publish_event") as mock_publish:
            publish_destroyed(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

            # Should publish both status update and destroyed event
            assert mock_publish.call_count >= 1

            calls = [call[0][0] for call in mock_publish.call_args_list]
            destroyed_events = [c for c in calls if c.get("event_type") == "range.destroyed"]

            assert len(destroyed_events) == 1


class TestPublishCancelled:
    """Tests for publish_cancelled() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_cancelled_event(self, mock_sns_env):
        """Publishes range.cancelled event."""
        from events import publish_cancelled

        with patch("events._publish_event") as mock_publish:
            publish_cancelled(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "range.cancelled"
            assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert event["range_id"] == 42
            assert event["user_id"] == 1


# =============================================================================
# NGFW Event Publishing Tests
# =============================================================================


class TestPublishNgfwEvent:
    """Tests for publish_ngfw_event() unified function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_ngfw_event_with_required_fields(self, mock_sns_env):
        """Publishes event with all required UUID fields."""
        from events import publish_ngfw_event

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="provisioning",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "ngfw.event"
            assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert event["instance_id"] == "660e8400-e29b-41d4-a716-446655440001"
            assert event["app_id"] == "770e8400-e29b-41d4-a716-446655440002"
            assert event["status"] == "provisioning"
            assert "event_id" in event
            assert "timestamp" in event

    def test_publishes_ngfw_event_with_serial_number(self, mock_sns_env):
        """Publishes ready event with serial_number."""
        from events import publish_ngfw_event

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="ready",
                serial_number="007951000123456",
            )

            event = mock_publish.call_args[0][0]
            assert event["status"] == "ready"
            assert event["serial_number"] == "007951000123456"

    def test_publishes_ngfw_event_without_serial_number(self, mock_sns_env):
        """Publishes event without serial_number (e.g., for failed status)."""
        from events import publish_ngfw_event

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="failed",
            )

            event = mock_publish.call_args[0][0]
            assert event["status"] == "failed"
            assert "serial_number" not in event
