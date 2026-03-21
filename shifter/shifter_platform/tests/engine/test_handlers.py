"""Tests for Engine handlers."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from shared.enums import ResourceStatus


def log_contains(caplog, message: str) -> bool:
    """Check if any log record contains the given message.

    Works with both plain text and JSON structured logging.
    """
    return any(message in record.message for record in caplog.records)


class TestProcessEvent:
    """Tests for process_event dispatcher."""

    def test_routes_range_events_to_range_handler(self):
        """Dispatcher routes range.* events to process_range_event."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("engine.handlers.process_range_event") as mock_range_handler:
            process_event(message)
            mock_range_handler.assert_called_once_with(message)

    def test_routes_ngfw_events_to_ngfw_handler(self):
        """Dispatcher routes ngfw.* events to process_ngfw_event."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "ngfw.status.updated",
                    "ngfw_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler:
            process_event(message)
            mock_ngfw_handler.assert_called_once_with(message)

    def test_ignores_unknown_event_types(self, caplog):
        """Dispatcher ignores events with unknown event_type prefix."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "unknown.event",
                    "some_id": 1,
                }
            )
        }

        with (
            caplog.at_level(logging.DEBUG, logger="engine.handlers"),
            patch("engine.handlers.process_range_event") as mock_range_handler,
            patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()
            assert log_contains(caplog, "Ignoring unknown event_type")

    def test_handles_missing_event_type(self, caplog):
        """Dispatcher handles messages without event_type gracefully."""
        from engine.handlers import process_event

        message = {"Message": json.dumps({"range_id": 1})}

        with (
            caplog.at_level(logging.DEBUG, logger="engine.handlers"),
            patch("engine.handlers.process_range_event") as mock_range_handler,
            patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()


class TestParseSnsMessage:
    """Tests for parse_sns_message helper."""

    def test_parses_sns_wrapped_message(self):
        """Function unwraps SNS envelope to get event payload."""
        from engine.handlers import parse_sns_message

        sns_message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1
        assert result["user_id"] == 42

    def test_parses_string_input(self):
        """Function parses string JSON input."""
        from engine.handlers import parse_sns_message

        sns_message = json.dumps(
            {
                "Message": json.dumps(
                    {
                        "event_type": "range.status.updated",
                        "range_id": 1,
                    }
                )
            }
        )

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_handles_non_wrapped_message(self):
        """Function handles direct event payload (no SNS wrapper)."""
        from engine.handlers import parse_sns_message

        direct_message = {
            "event_type": "range.status.updated",
            "range_id": 1,
            "user_id": 42,
        }

        result = parse_sns_message(direct_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


@pytest.fixture
def user():
    """Create a mock user (no database required)."""
    mock_user = MagicMock()
    mock_user.id = 42
    mock_user.username = "testuser"
    return mock_user


@pytest.fixture
def mock_range():
    """Create a mock Range object factory (no database required)."""

    def _make(range_id=1, user_id=42, status=ResourceStatus.PENDING.value, **kwargs):
        obj = MagicMock()
        obj.id = range_id
        obj.user_id = user_id
        obj.status = status
        obj.ready_at = kwargs.get("ready_at")
        obj.destroyed_at = kwargs.get("destroyed_at")
        obj.error_message = kwargs.get("error_message", "")
        obj.provisioned_instances = kwargs.get("provisioned_instances")
        return obj

    return _make


class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_status(self, user, mock_range):
        """Handler updates Range.status from event."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PENDING.value)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert range_obj.status == ResourceStatus.PROVISIONING.value
        range_obj.save.assert_called_once()

    def test_sets_ready_at_on_ready_status(self, user, mock_range):
        """Handler sets ready_at when transitioning to READY."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PROVISIONING.value, ready_at=None)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert range_obj.status == ResourceStatus.READY.value
        assert range_obj.ready_at is not None
        range_obj.save.assert_called_once()

    def test_sets_destroyed_at_on_destroyed_status(self, user, mock_range):
        """Handler sets destroyed_at when transitioning to DESTROYED."""
        from engine.handlers import process_range_event

        range_obj = mock_range(
            range_id=1,
            user_id=user.id,
            status=ResourceStatus.DESTROYING.value,
            destroyed_at=None,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.DESTROYED.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert range_obj.status == ResourceStatus.DESTROYED.value
        assert range_obj.destroyed_at is not None
        range_obj.save.assert_called_once()

    def test_stores_error_message_on_failed_status(self, user, mock_range):
        """Handler stores error_message when transitioning to FAILED."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PROVISIONING.value)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user.id,
                    "error_message": "Subnet exhausted",
                }
            )
        }

        with (
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert range_obj.status == ResourceStatus.FAILED.value
        assert range_obj.error_message == "Subnet exhausted"

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_unknown_event_types(self, caplog):
        """Handler ignores events that are not recognized."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.unknown_event",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert log_contains(caplog, "Ignoring event_type")

    # ---------------------------------------------------------------------
    # Error handling - missing data
    # ---------------------------------------------------------------------

    def test_handles_missing_range(self, caplog):
        """Handler logs warning when Range not found."""
        from engine.handlers import process_range_event
        from engine.models import Range

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999999,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with (
            caplog.at_level(logging.WARNING, logger="engine.handlers"),
            patch(
                "engine.handlers.Range.objects.get",
                side_effect=Range.DoesNotExist,
            ),
        ):
            process_range_event(message)

        assert log_contains(caplog, "Range not found")
        assert log_contains(caplog, "999999")

    def test_handles_user_id_mismatch(self, user, mock_range, caplog):
        """Handler logs error when user_id doesn't match Range."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PENDING.value)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 999999,  # Wrong user
                }
            )
        }

        with (
            caplog.at_level(logging.ERROR, logger="engine.handlers"),
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
        ):
            process_range_event(message)

        assert log_contains(caplog, "user_id mismatch")
        assert log_contains(caplog, "999999")

        # Status should be unchanged
        assert range_obj.status == ResourceStatus.PENDING.value
        range_obj.save.assert_not_called()

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, user, mock_range, caplog):
        """Handler logs exception when database save fails."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PENDING.value)
        range_obj.save.side_effect = Exception("DB down")

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            caplog.at_level(logging.ERROR, logger="engine.handlers"),
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
        ):
            process_range_event(message)

        assert log_contains(caplog, "DB error saving Range")
        assert log_contains(caplog, "range_id=1")

    # ---------------------------------------------------------------------
    # Logging - success
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, user, mock_range, caplog):
        """Handler logs INFO when status successfully updated."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PENDING.value)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            caplog.at_level(logging.INFO, logger="engine.handlers"),
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert log_contains(caplog, "Engine updated Range")
        assert log_contains(caplog, "range_id=1")
        assert log_contains(caplog, "pending")
        assert log_contains(caplog, "provisioning")

    def test_logs_debug_on_event_ignore(self, caplog):
        """Handler logs DEBUG when ignoring non-status events."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.destroyed",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert log_contains(caplog, "Ignoring event_type")
        assert log_contains(caplog, "range.destroyed")

    # ---------------------------------------------------------------------
    # Edge cases
    # ---------------------------------------------------------------------

    def test_failed_without_error_message(self, user, mock_range):
        """Handler handles FAILED status even without error_message."""
        from engine.handlers import process_range_event

        range_obj = mock_range(range_id=1, user_id=user.id, status=ResourceStatus.PROVISIONING.value)

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user.id,
                    # No error_message
                }
            )
        }

        with (
            patch("engine.handlers.Range.objects.get", return_value=range_obj),
            patch("engine.handlers.audit_log_system_event"),
        ):
            process_range_event(message)

        assert range_obj.status == ResourceStatus.FAILED.value
        # error_message not set by handler when not in event payload
        range_obj.save.assert_called_once()


class TestHandleProvisioned:
    """Tests for _handle_provisioned handler.

    _handle_provisioned is now notification-only (log only, no DB updates).
    The provisioner writes all state directly to the database before
    publishing the range.provisioned event.
    """

    def test_logs_provisioned_event(self, caplog):
        """Handler logs INFO when receiving provisioned event."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "event_id": "evt-12345",
                    "request_id": "550e8400-e29b-41d4-a716-446655440000",
                    "range_id": 42,
                    "user_id": 7,
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            process_range_event(message)

        assert log_contains(caplog, "Engine received range.provisioned")
        assert log_contains(caplog, "request_id=550e8400-e29b-41d4-a716-446655440000")
        assert log_contains(caplog, "range_id=42")
        assert log_contains(caplog, "event_id=evt-12345")

    def test_does_not_call_save(self, mock_range):
        """Handler does not modify Range model (provisioner writes directly)."""
        from engine.handlers import process_range_event

        range_obj = mock_range(
            range_id=1,
            user_id=42,
            status=ResourceStatus.PROVISIONING.value,
            provisioned_instances=None,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "event_id": "evt-12345",
                    "request_id": "550e8400-e29b-41d4-a716-446655440000",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("engine.handlers.Range.objects.get", return_value=range_obj):
            process_range_event(message)

        # Handler is log-only - save should not be called
        range_obj.save.assert_not_called()

    def test_handles_event_without_range_in_db(self, caplog):
        """Handler logs event even if Range not in DB (notification-only)."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "event_id": "evt-12345",
                    "request_id": "550e8400-e29b-41d4-a716-446655440000",
                    "range_id": 999999,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            # Should not raise - just log
            process_range_event(message)

        assert log_contains(caplog, "Engine received range.provisioned")
        assert log_contains(caplog, "range_id=999999")
