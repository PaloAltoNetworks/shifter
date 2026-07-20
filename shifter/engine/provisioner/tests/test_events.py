"""Tests for durable event enqueueing in events.py.

Phase 1 (#476): _publish_event is renamed to _enqueue_event and now writes
durably to the outbox via provisioner_db.enqueue_event_outbox instead of
publishing directly to SNS. Failures propagate to the caller (no swallowing).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from events import (
    _enqueue_event,
    _get_sns_topic_arn,
    _publish_event,
    publish_cancelled,
    publish_destroyed,
    publish_failed,
    publish_ngfw_event,
    publish_ready,
    publish_status_update,
)


def _make_mock_db():
    """Return (mock_conn, mock_cur) backed by a fully stubbed psycopg connection."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    return mock_conn, mock_cur


@pytest.fixture
def mock_sns_env(monkeypatch):
    """Set up SNS environment variables."""
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv(
        "SNS_RANGE_EVENTS_ARN",
        "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
    )


@pytest.fixture
def db_env(monkeypatch):
    """Set minimal DB env vars so get_db_connection() reaches psycopg.connect."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("DB_PASSWORD", "testpass")


class TestGetSNSTopicARN:
    """Tests for _get_sns_topic_arn() function."""

    def test_prefers_generic_topic_id_when_set(self, monkeypatch):
        """Returns RANGE_EVENTS_TOPIC_ID when present."""
        monkeypatch.setenv("RANGE_EVENTS_TOPIC_ID", "projects/test/topics/range-events")
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:ignored")

        assert _get_sns_topic_arn() == "projects/test/topics/range-events"

    def test_returns_arn_from_environment(self, monkeypatch):
        """Returns SNS_RANGE_EVENTS_ARN from environment."""
        monkeypatch.setenv(
            "SNS_RANGE_EVENTS_ARN",
            "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events",
        )

        expected = "arn:aws:sns:us-east-2:123456789012:dev-portal-range-events"
        assert _get_sns_topic_arn() == expected

    def test_raises_when_arn_not_set(self, monkeypatch):
        """Raises ValueError when SNS_RANGE_EVENTS_ARN not set."""
        monkeypatch.delenv("RANGE_EVENTS_TOPIC_ID", raising=False)
        monkeypatch.delenv("SNS_RANGE_EVENTS_ARN", raising=False)

        with pytest.raises(ValueError, match="RANGE_EVENTS_TOPIC_ID"):
            _get_sns_topic_arn()


class TestEnqueueEvent:
    """Tests for _enqueue_event() — the durable outbox writer."""

    def test_raises_when_enqueue_fails(self, db_env):
        """_enqueue_event propagates exceptions when the durable write fails."""
        with (
            patch("psycopg.connect", side_effect=RuntimeError("db down")),
            pytest.raises(RuntimeError, match="db down"),
        ):
            _enqueue_event(
                {
                    "event_type": "range.status.updated",
                    "event_id": str(uuid4()),
                    "range_id": 42,
                }
            )

    def test_enqueue_delegates_to_provisioner_db(self, db_env):
        """_enqueue_event writes the full event dict to the outbox table."""
        event = {
            "event_type": "range.status.updated",
            "event_id": str(uuid4()),
            "range_id": 42,
            "user_id": 1,
            "new_status": "provisioning",
        }
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            _enqueue_event(event)

        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[0] == str(event["event_id"])
        assert params[1] == event["event_type"]
        assert json.loads(params[2]) == event

    def test_publish_event_alias_delegates_to_enqueue(self, db_env):
        """_publish_event alias also writes the event to the outbox table."""
        event = {"event_type": "range.status.updated", "event_id": str(uuid4()), "range_id": 1}
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            _publish_event(event)

        mock_cur.execute.assert_called_once()
        params = mock_cur.execute.call_args[0][1]
        assert params[1] == event["event_type"]
        assert json.loads(params[2])["range_id"] == event["range_id"]


class TestPublishStatusUpdate:
    """Tests for publish_status_update() function."""

    def test_publishes_status_change_event(self, mock_sns_env, db_env):
        """Publishes event with status transition details."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="provisioning",
            )

        mock_cur.execute.assert_called_once()
        event = json.loads(mock_cur.execute.call_args[0][1][2])

        assert event["event_type"] == "range.status.updated"
        assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert event["range_id"] == 42
        assert event["user_id"] == 1
        assert event["new_status"] == "provisioning"

    def test_includes_error_message_when_provided(self, mock_sns_env, db_env):
        """Error message is included in event when provided."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="failed",
                error_message="Subnet exhausted",
            )

        event = json.loads(mock_cur.execute.call_args[0][1][2])
        assert event["error_message"] == "Subnet exhausted"


class TestPublishReady:
    """Tests for publish_ready() function.

    publish_ready() is notification-only. All state (instances, subnets) is
    written directly to the database by the provisioner before this event
    is published.
    """

    def test_publishes_ready_and_provisioned_events(self, mock_sns_env, db_env):
        """Publishes status update (ready) and provisioned events."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

        assert mock_cur.execute.call_count == 2
        payloads = [json.loads(c[0][1][2]) for c in mock_cur.execute.call_args_list]
        event_types = [e.get("event_type") for e in payloads]

        assert "range.status.updated" in event_types
        assert "range.provisioned" in event_types

    def test_provisioned_event_is_notification_only(self, mock_sns_env, db_env):
        """Provisioned event has only identification fields, no state data."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

        payloads = [json.loads(c[0][1][2]) for c in mock_cur.execute.call_args_list]
        provisioned_events = [e for e in payloads if e.get("event_type") == "range.provisioned"]

        assert len(provisioned_events) == 1
        event = provisioned_events[0]

        assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert event["range_id"] == 42
        assert event["user_id"] == 1
        assert "event_id" in event
        assert "timestamp" in event
        assert "instances" not in event
        assert "subnets" not in event
        assert "pulumi_stack" not in event

    def test_status_update_sets_ready_status(self, mock_sns_env, db_env):
        """Status update event has new_status='ready'."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ready(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

        payloads = [json.loads(c[0][1][2]) for c in mock_cur.execute.call_args_list]
        status_events = [e for e in payloads if e.get("event_type") == "range.status.updated"]

        assert len(status_events) == 1
        assert status_events[0]["new_status"] == "ready"


class TestPublishLifecycleEvents:
    """Tests for publish_failed(), publish_destroyed(), publish_cancelled()."""

    def test_publish_failed_includes_error_message(self, mock_sns_env, db_env):
        """Publishes status update with failed status and error message."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_failed(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                error_message="Instance launch failed",
            )

        mock_cur.execute.assert_called_once()
        event = json.loads(mock_cur.execute.call_args[0][1][2])

        assert event["new_status"] == "failed"
        assert event["error_message"] == "Instance launch failed"

    def test_publish_destroyed_sends_event(self, mock_sns_env, db_env):
        """Publishes range.destroyed event."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_destroyed(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

        assert mock_cur.execute.call_count >= 1
        payloads = [json.loads(c[0][1][2]) for c in mock_cur.execute.call_args_list]
        destroyed_events = [e for e in payloads if e.get("event_type") == "range.destroyed"]

        assert len(destroyed_events) == 1

    def test_publish_cancelled_sends_event(self, mock_sns_env, db_env):
        """Publishes range.cancelled event."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_cancelled(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
            )

        mock_cur.execute.assert_called_once()
        event = json.loads(mock_cur.execute.call_args[0][1][2])

        assert event["event_type"] == "range.cancelled"
        assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert event["range_id"] == 42
        assert event["user_id"] == 1


class TestPublishNgfwEvent:
    """Tests for publish_ngfw_event() unified function."""

    def test_publishes_ngfw_event_with_required_fields(self, mock_sns_env, db_env):
        """Publishes event with all required UUID fields."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="provisioning",
            )

        mock_cur.execute.assert_called_once()
        event = json.loads(mock_cur.execute.call_args[0][1][2])

        assert event["event_type"] == "ngfw.event"
        assert event["request_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert event["instance_id"] == "660e8400-e29b-41d4-a716-446655440001"
        assert event["app_id"] == "770e8400-e29b-41d4-a716-446655440002"
        assert event["status"] == "provisioning"
        assert "event_id" in event
        assert "timestamp" in event

    def test_publishes_ngfw_event_with_serial_number(self, mock_sns_env, db_env):
        """Publishes ready event with serial_number."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="ready",
                serial_number="007951000123456",
            )

        event = json.loads(mock_cur.execute.call_args[0][1][2])
        assert event["status"] == "ready"
        assert event["serial_number"] == "007951000123456"

    def test_publishes_ngfw_event_without_serial_number(self, mock_sns_env, db_env):
        """Publishes event without serial_number (e.g., for failed status)."""
        mock_conn, mock_cur = _make_mock_db()
        with patch("psycopg.connect", return_value=mock_conn):
            publish_ngfw_event(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                instance_id="660e8400-e29b-41d4-a716-446655440001",
                app_id="770e8400-e29b-41d4-a716-446655440002",
                status="failed",
            )

        event = json.loads(mock_cur.execute.call_args[0][1][2])
        assert event["status"] == "failed"
        assert "serial_number" not in event


class TestStatusBuilderEvent:
    """Verify that status builders enqueue (not swallow) on failure."""

    def test_publish_status_update_propagates_enqueue_failure(self, db_env):
        """publish_status_update raises if the outbox write fails."""
        with (
            patch("psycopg.connect", side_effect=RuntimeError("db error")),
            pytest.raises(RuntimeError, match="db error"),
        ):
            publish_status_update(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                range_id=42,
                user_id=1,
                new_status="provisioning",
            )
