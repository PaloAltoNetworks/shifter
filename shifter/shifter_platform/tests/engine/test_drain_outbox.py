"""Tests for drain_range_event_outbox management command.

Drives real ORM rows with a real SQLite test DB (ADR-019).
boto3 SNS client is patched at the real cloud boundary.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases=["default"])

# Fixed topic ARN used across tests.
TOPIC_ID = "arn:aws:sns:us-east-2:123456789012:range-events"

_CMD = "drain_range_event_outbox"


def _make_row(
    *,
    event_type: str = "range.ready",
    status: str = "PENDING",
    attempts: int = 0,
    max_attempts: int = 10,
    next_attempt_at=None,
):
    """Insert a RangeEventOutbox row into the test DB."""
    from engine.models import RangeEventOutbox

    return RangeEventOutbox.objects.create(
        event_id=uuid.uuid4(),
        event_type=event_type,
        payload={"range_id": str(uuid.uuid4()), "event_type": event_type},
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        next_attempt_at=next_attempt_at if next_attempt_at is not None else timezone.now() - timedelta(seconds=1),
    )


def _run(settings_fixture=None, topic_id: str = TOPIC_ID, sns_client=None, **kwargs):
    """Call drain command with a mocked SNS client; return (mock_sns, stdout)."""
    if sns_client is None:
        sns_client = MagicMock()
    stdout = StringIO()
    if settings_fixture is not None:
        settings_fixture.RANGE_EVENTS_TOPIC_ID = topic_id
    with patch("boto3.client", return_value=sns_client):
        call_command(_CMD, stdout=stdout, **kwargs)
    return sns_client, stdout.getvalue()


def _failing_sns(msg: str = "transient"):
    """Return a mock SNS client whose publish raises ClientError."""
    mock_sns = MagicMock()
    mock_sns.publish.side_effect = ClientError({"Error": {"Code": "500", "Message": msg}}, "Publish")
    return mock_sns


class TestDrainOutboxPublishSuccess:
    """PENDING row within due window is published and marked PUBLISHED."""

    def test_pending_row_becomes_published(self, settings):
        row = _make_row()
        _run(settings)
        row.refresh_from_db()
        assert row.status == "PUBLISHED"

    def test_published_at_is_set(self, settings):
        row = _make_row()
        before = timezone.now()
        _run(settings)
        row.refresh_from_db()
        assert row.published_at is not None
        assert row.published_at >= before

    def test_publish_called_with_json_payload(self, settings):
        row = _make_row()
        mock_sns, _ = _run(settings)
        message = mock_sns.publish.call_args.kwargs["Message"]
        assert json.loads(message) == row.payload

    def test_publish_called_with_topic_id(self, settings):
        _make_row()
        mock_sns, _ = _run(settings)
        assert mock_sns.publish.call_args.kwargs["TopicArn"] == TOPIC_ID

    def test_publish_called_with_event_type_attribute(self, settings):
        _make_row(event_type="range.destroyed")
        mock_sns, _ = _run(settings)
        msg_attrs = mock_sns.publish.call_args.kwargs["MessageAttributes"]
        assert msg_attrs == {"event_type": {"DataType": "String", "StringValue": "range.destroyed"}}

    def test_multiple_pending_rows_all_published(self, settings):
        rows = [_make_row() for _ in range(3)]
        mock_sns, _ = _run(settings)
        assert mock_sns.publish.call_count == 3
        for row in rows:
            row.refresh_from_db()
            assert row.status == "PUBLISHED"


class TestDrainOutboxTransientFailure:
    """Transient ClientError increments attempts, sets backoff, status stays PENDING."""

    def test_transient_failure_increments_attempts(self, settings):
        row = _make_row(attempts=0, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.attempts == 1

    def test_transient_failure_status_remains_pending(self, settings):
        row = _make_row(attempts=0, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.status == "PENDING"

    def test_transient_failure_sets_backoff_on_next_attempt_at(self, settings):
        row = _make_row(attempts=0, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID
        before = timezone.now()

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        # After 1st failure (attempts becomes 1): backoff = min(60 * 2^0, 3600) = 60s
        assert row.next_attempt_at > before + timedelta(seconds=55)
        assert row.next_attempt_at < before + timedelta(seconds=65)

    def test_transient_failure_sets_last_error_bounded(self, settings):
        row = _make_row()
        long_msg = "x" * 1000
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns(long_msg)):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.last_error is not None
        assert len(row.last_error) <= 500

    def test_second_failure_doubles_backoff(self, settings):
        row = _make_row(attempts=1, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID
        before = timezone.now()

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        # After 2nd failure (attempts becomes 2): backoff = min(60 * 2^1, 3600) = 120s
        assert row.next_attempt_at > before + timedelta(seconds=115)
        assert row.next_attempt_at < before + timedelta(seconds=125)


class TestDrainOutboxExhaustion:
    """Row reaching max_attempts is moved to DLQ."""

    def test_last_attempt_moves_to_dlq(self, settings):
        row = _make_row(attempts=9, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.status == "DLQ"
        assert row.attempts == 10

    def test_penultimate_attempt_stays_pending(self, settings):
        row = _make_row(attempts=8, max_attempts=10)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.status == "PENDING"
        assert row.attempts == 9

    def test_custom_max_attempts_honored(self, settings):
        row = _make_row(attempts=2, max_attempts=3)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        assert row.status == "DLQ"


class TestDrainOutboxSkipRows:
    """Already-published or future-scheduled rows are not processed."""

    def test_already_published_row_is_skipped(self, settings):
        _make_row(status="PUBLISHED")
        mock_sns, _ = _run(settings)
        mock_sns.publish.assert_not_called()

    def test_dlq_row_is_skipped(self, settings):
        _make_row(status="DLQ")
        mock_sns, _ = _run(settings)
        mock_sns.publish.assert_not_called()

    def test_future_next_attempt_at_is_skipped(self, settings):
        _make_row(next_attempt_at=timezone.now() + timedelta(hours=1))
        mock_sns, _ = _run(settings)
        mock_sns.publish.assert_not_called()

    def test_only_due_rows_are_processed(self, settings):
        due = _make_row(next_attempt_at=timezone.now() - timedelta(minutes=1))
        not_due = _make_row(next_attempt_at=timezone.now() + timedelta(hours=1))
        _make_row(status="PUBLISHED", next_attempt_at=timezone.now() - timedelta(minutes=1))

        mock_sns, _ = _run(settings)

        assert mock_sns.publish.call_count == 1
        due.refresh_from_db()
        assert due.status == "PUBLISHED"
        not_due.refresh_from_db()
        assert not_due.status == "PENDING"


class TestDrainOutboxMissingTopicId:
    """Missing RANGE_EVENTS_TOPIC_ID configuration raises CommandError."""

    def test_raises_command_error_when_no_topic_id(self, settings, monkeypatch):
        settings.RANGE_EVENTS_TOPIC_ID = ""
        monkeypatch.delenv("RANGE_EVENTS_TOPIC_ID", raising=False)
        monkeypatch.delenv("SNS_RANGE_EVENTS_ARN", raising=False)

        with pytest.raises(CommandError, match="RANGE_EVENTS_TOPIC_ID"):
            call_command(_CMD, stdout=StringIO())


class TestDrainOutboxBatchSize:
    """--batch-size limits how many rows are processed per run."""

    def test_batch_size_limits_processed_rows(self, settings):
        [_make_row() for _ in range(5)]
        mock_sns, _ = _run(settings, batch_size=2)
        assert mock_sns.publish.call_count == 2

    def test_default_batch_size_processes_all_within_limit(self, settings):
        [_make_row() for _ in range(3)]
        mock_sns, _ = _run(settings)
        assert mock_sns.publish.call_count == 3


class TestDrainOutboxBackoffCap:
    """Backoff is capped at 3600 seconds regardless of attempt count."""

    def test_high_attempt_count_backoff_capped(self, settings):
        # 20 attempts; backoff without cap would be 60 * 2^19 = 31457280s
        row = _make_row(attempts=20, max_attempts=100)
        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID
        before = timezone.now()

        with patch("boto3.client", return_value=_failing_sns()):
            call_command(_CMD, stdout=StringIO())

        row.refresh_from_db()
        # Backoff cap is 3600s
        assert row.next_attempt_at < before + timedelta(seconds=3601)
        assert row.next_attempt_at > before + timedelta(seconds=3595)


class TestDrainOutboxHeartbeat:
    """--loop mode touches the heartbeat file after each cycle."""

    def test_loop_touches_heartbeat(self, settings, tmp_path, monkeypatch):
        """One loop iteration must write the heartbeat file."""
        from engine.management.commands import drain_range_event_outbox as cmd_module

        heartbeat_file = tmp_path / "worker-outbox-drainer-heartbeat"
        monkeypatch.setattr(cmd_module, "HEARTBEAT_FILE", heartbeat_file)

        settings.RANGE_EVENTS_TOPIC_ID = TOPIC_ID
        call_count = 0

        def fake_sleep(_interval: int) -> None:
            nonlocal call_count
            call_count += 1
            # Stop the loop after the first sleep so the test terminates.
            raise KeyboardInterrupt

        # Patch time.sleep at the stdlib module level (root: "time") so the
        # target is not a first-party internal path and does not widen the
        # ADR-019 boundary-mock baseline.
        with (
            patch("boto3.client", return_value=MagicMock()),
            patch("time.sleep", side_effect=fake_sleep),
            pytest.raises(KeyboardInterrupt),
        ):
            call_command(_CMD, stdout=StringIO(), loop=True, interval=10)

        assert heartbeat_file.exists(), "heartbeat file must be written during loop iteration"
        assert call_count == 1
