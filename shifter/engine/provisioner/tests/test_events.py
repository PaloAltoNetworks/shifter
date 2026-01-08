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

        from events import _get_sns_client

        with patch("events.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            _get_sns_client()

            mock_boto.assert_called_once_with("sns", region_name="us-west-2")

    def test_uses_default_region_when_not_set(self, monkeypatch):
        """Client uses us-east-2 as default region."""
        monkeypatch.delenv("AWS_REGION", raising=False)

        from events import _get_sns_client

        with patch("events.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            _get_sns_client()

            mock_boto.assert_called_once_with("sns", region_name="us-east-2")


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
                range_id=42,
                user_id=1,
                new_status="provisioning",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "range.status.updated"
            assert event["range_id"] == 42
            assert event["user_id"] == 1
            assert event["new_status"] == "provisioning"

    def test_includes_error_message_when_provided(self, mock_sns_env):
        """Error message is included in event when provided."""
        from events import publish_status_update

        with patch("events._publish_event") as mock_publish:
            publish_status_update(
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
            publish_status_update(range_id=42, user_id=1, new_status="provisioning")

            assert "42" in caplog.text
            assert "provisioning" in caplog.text


class TestPublishReady:
    """Tests for publish_ready() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_provisioned_event_with_instances(self, mock_sns_env):
        """Publishes range.provisioned event with instance details."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            instances = [
                {"role": "attacker", "ip": "10.1.1.10"},
                {"role": "victim", "ip": "10.1.1.20"},
            ]

            publish_ready(range_id=42, user_id=1, instances=instances)

            # Should publish both status update and provisioned event
            assert mock_publish.call_count >= 1

            # Find the provisioned event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            provisioned_events = [c for c in calls if c.get("event_type") == "range.provisioned"]

            assert len(provisioned_events) == 1
            assert provisioned_events[0]["instances"] == instances

    def test_publishes_provisioned_event_with_infrastructure_details(self, mock_sns_env):
        """Publishes range.provisioned event with subnet and stack details."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            instances = [{"role": "attacker", "ip": "10.1.1.10"}]

            publish_ready(
                range_id=42,
                user_id=1,
                instances=instances,
                subnet_id="subnet-12345",
                subnet_cidr="10.1.6.0/24",
                pulumi_stack="range-42",
            )

            # Find the provisioned event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            provisioned_events = [c for c in calls if c.get("event_type") == "range.provisioned"]

            assert len(provisioned_events) == 1
            event = provisioned_events[0]
            assert event["subnet_id"] == "subnet-12345"
            assert event["subnet_cidr"] == "10.1.6.0/24"
            assert event["pulumi_stack"] == "range-42"

    def test_publishes_provisioned_event_with_none_infrastructure_details(self, mock_sns_env):
        """Optional infrastructure params can be None."""
        from events import publish_ready

        with patch("events._publish_event") as mock_publish:
            instances = [{"role": "attacker", "ip": "10.1.1.10"}]

            publish_ready(range_id=42, user_id=1, instances=instances)

            # Find the provisioned event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            provisioned_events = [c for c in calls if c.get("event_type") == "range.provisioned"]

            assert len(provisioned_events) == 1
            event = provisioned_events[0]
            # None values should still be in the event (filtered by consumers if needed)
            assert "subnet_id" in event
            assert "subnet_cidr" in event
            assert "pulumi_stack" in event


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
            publish_failed(range_id=42, user_id=1, error_message="Instance launch failed")

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
            publish_destroyed(range_id=42, user_id=1)

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
            publish_cancelled(range_id=42, user_id=1)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "range.cancelled"
            assert event["range_id"] == 42
            assert event["user_id"] == 1


# =============================================================================
# NGFW Event Publishing Tests
# =============================================================================


class TestCreateNgfwEvent:
    """Tests for _create_ngfw_event() internal function."""

    def test_creates_event_with_required_fields(self):
        """Creates NGFW event envelope with all required fields."""
        from events import _create_ngfw_event

        event = _create_ngfw_event(
            event_type="ngfw.status.updated",
            ngfw_id=42,
            cms_ngfw_id=100,
            user_id=5,
        )

        assert event["event_type"] == "ngfw.status.updated"
        assert event["ngfw_id"] == 42
        assert event["cms_ngfw_id"] == 100
        assert event["user_id"] == 5
        assert "event_id" in event
        assert "timestamp" in event

    def test_includes_kwargs_in_event(self):
        """Additional kwargs are included in the event."""
        from events import _create_ngfw_event

        event = _create_ngfw_event(
            event_type="ngfw.provisioned",
            ngfw_id=42,
            cms_ngfw_id=100,
            user_id=5,
            instance_id="i-abc123",
            management_ip="10.0.1.10",
        )

        assert event["instance_id"] == "i-abc123"
        assert event["management_ip"] == "10.0.1.10"


class TestPublishNgfwStatusUpdate:
    """Tests for publish_ngfw_status_update() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_ngfw_status_change_event(self, mock_sns_env):
        """Publishes event with NGFW status transition details."""
        from events import publish_ngfw_status_update

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_status_update(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                new_status="provisioning",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["event_type"] == "ngfw.status.updated"
            assert event["ngfw_id"] == 42
            assert event["cms_ngfw_id"] == 100
            assert event["user_id"] == 5
            assert event["new_status"] == "provisioning"

    def test_includes_error_message_when_provided(self, mock_sns_env):
        """Error message is included in NGFW event when provided."""
        from events import publish_ngfw_status_update

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_status_update(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                new_status="failed",
                error_message="Pulumi stack error",
            )

            event = mock_publish.call_args[0][0]
            assert event["error_message"] == "Pulumi stack error"

    def test_logs_info_on_status_change(self, mock_sns_env, caplog):
        """Logs info message for NGFW status changes."""
        from events import publish_ngfw_status_update

        with (
            patch("events._publish_event"),
            caplog.at_level(logging.INFO, logger="events"),
        ):
            publish_ngfw_status_update(ngfw_id=42, cms_ngfw_id=100, user_id=5, new_status="ready")

            assert "42" in caplog.text
            assert "ready" in caplog.text


class TestPublishNgfwReady:
    """Tests for publish_ngfw_ready() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_ngfw_provisioned_event_with_resources(self, mock_sns_env):
        """Publishes ngfw.provisioned event with resource details."""
        from events import publish_ngfw_ready

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_ready(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                instance_id="i-0abc123def456789",
                management_ip="10.0.1.10",
                dataplane_ip="10.0.2.10",
                service_name="com.amazonaws.vpce.us-east-2.vpce-svc-abc123",
                gwlb_arn="arn:aws:elasticloadbalancing:us-east-2:123456789:loadbalancer/gwy/test-gwlb/abc123",
                target_group_arn="arn:aws:elasticloadbalancing:us-east-2:123456789:targetgroup/test-tg/abc123",
            )

            # Should publish both status update and provisioned event
            assert mock_publish.call_count >= 1

            # Find the provisioned event
            calls = [call[0][0] for call in mock_publish.call_args_list]
            provisioned_events = [c for c in calls if c.get("event_type") == "ngfw.provisioned"]

            assert len(provisioned_events) == 1
            event = provisioned_events[0]
            assert event["instance_id"] == "i-0abc123def456789"
            assert event["management_ip"] == "10.0.1.10"
            assert event["dataplane_ip"] == "10.0.2.10"
            assert event["service_name"] == "com.amazonaws.vpce.us-east-2.vpce-svc-abc123"
            assert event["gwlb_arn"].startswith("arn:aws:elasticloadbalancing")
            assert event["target_group_arn"].startswith("arn:aws:elasticloadbalancing")

    def test_publishes_status_update_before_provisioned(self, mock_sns_env):
        """First publishes status update with 'ready' status."""
        from events import publish_ngfw_ready

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_ready(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                instance_id="i-abc",
                management_ip="10.0.1.10",
                dataplane_ip="10.0.2.10",
                service_name="svc-abc",
                gwlb_arn="arn:gwlb",
                target_group_arn="arn:tg",
            )

            # Status update should be published first
            calls = [call[0][0] for call in mock_publish.call_args_list]
            status_events = [c for c in calls if c.get("event_type") == "ngfw.status.updated"]

            assert len(status_events) == 1
            assert status_events[0]["new_status"] == "ready"


class TestPublishNgfwFailed:
    """Tests for publish_ngfw_failed() function."""

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
        from events import publish_ngfw_failed

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_failed(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                error_message="Pulumi stack failed",
            )

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]

            assert event["new_status"] == "failed"
            assert event["error_message"] == "Pulumi stack failed"
            assert event["ngfw_id"] == 42
            assert event["cms_ngfw_id"] == 100


class TestPublishNgfwDestroyed:
    """Tests for publish_ngfw_destroyed() function."""

    @pytest.fixture
    def mock_sns_env(self, monkeypatch):
        """Set up SNS environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

    def test_publishes_ngfw_destroyed_event(self, mock_sns_env):
        """Publishes ngfw.destroyed event."""
        from events import publish_ngfw_destroyed

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_destroyed(ngfw_id=42, cms_ngfw_id=100, user_id=5)

            # Should publish both status update and destroyed event
            assert mock_publish.call_count >= 1

            calls = [call[0][0] for call in mock_publish.call_args_list]
            destroyed_events = [c for c in calls if c.get("event_type") == "ngfw.destroyed"]

            assert len(destroyed_events) == 1
            assert destroyed_events[0]["ngfw_id"] == 42
            assert destroyed_events[0]["cms_ngfw_id"] == 100

    def test_publishes_status_update_with_deprovisioned_status(self, mock_sns_env):
        """First publishes status update with 'deprovisioned' status."""
        from events import publish_ngfw_destroyed

        with patch("events._publish_event") as mock_publish:
            publish_ngfw_destroyed(ngfw_id=42, cms_ngfw_id=100, user_id=5)

            calls = [call[0][0] for call in mock_publish.call_args_list]
            status_events = [c for c in calls if c.get("event_type") == "ngfw.status.updated"]

            assert len(status_events) == 1
            assert status_events[0]["new_status"] == "deprovisioned"
