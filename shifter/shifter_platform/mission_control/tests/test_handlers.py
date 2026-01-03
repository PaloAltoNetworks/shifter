"""Tests for Mission Control handlers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestParseSnsMessage:
    """Tests for parse_sns_message helper."""

    def test_parses_sns_wrapped_message(self):
        """Function unwraps SNS envelope to get event payload."""
        from mission_control.handlers import parse_sns_message

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
        from mission_control.handlers import parse_sns_message

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
        from mission_control.handlers import parse_sns_message

        direct_message = {
            "event_type": "range.status.updated",
            "range_id": 1,
            "user_id": 42,
        }

        result = parse_sns_message(direct_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


@pytest.mark.django_db
class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - broadcast to channel layer
    # ---------------------------------------------------------------------

    def test_broadcasts_status_update_to_channel_layer(self):
        """Handler broadcasts status update to Django Channels group."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            # Verify async_to_sync was called with group_send
            mock_async_to_sync.assert_called_once()

            # Verify the sync wrapper was called with correct args
            mock_send.assert_called_once()
            args, _ = mock_send.call_args

            # Verify group name
            assert args[0] == "range_status_1"

            # Verify message content
            sent_message = args[1]
            assert sent_message["type"] == "range.status"
            assert sent_message["range_id"] == 1
            assert sent_message["new_status"] == RangeStatus.PROVISIONING.value
            assert sent_message["old_status"] == RangeStatus.PENDING.value

    def test_broadcasts_error_message_when_present(self):
        """Handler includes error_message in broadcast when present."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 2,
                    "new_status": RangeStatus.FAILED.value,
                    "old_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                    "error_message": "Subnet exhausted",
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            # Verify error_message included
            args, _ = mock_send.call_args
            sent_message = args[1]
            assert sent_message["error_message"] == "Subnet exhausted"

    def test_broadcasts_null_error_message_when_not_present(self):
        """Handler includes null error_message when not in event."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 3,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            # Verify error_message is None
            args, _ = mock_send.call_args
            sent_message = args[1]
            assert sent_message["error_message"] is None

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_non_status_events(self):
        """Handler ignores events that are not range.status.updated."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": 4,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            # Should NOT have broadcast (async_to_sync not called)
            mock_async_to_sync.assert_not_called()

    # ---------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_broadcast(self):
        """Handler logs INFO when broadcast succeeds."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 5,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("mission_control.handlers.logger") as mock_logger,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

        # Verify logger.info was called with expected content
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "MC broadcast to group" in call_args[0]
        assert "range_status_5" in call_args[1]
        assert call_args[2] == 5  # range_id

    def test_logs_debug_on_event_ignore(self):
        """Handler logs DEBUG when ignoring non-status events."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.destroyed",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("mission_control.handlers.logger") as mock_logger,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

        # Verify logger.debug was called with expected content
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args[0]
        assert "Ignoring event_type" in call_args[0]
        assert call_args[1] == "range.destroyed"

    # ---------------------------------------------------------------------
    # Handler is callable
    # ---------------------------------------------------------------------

    def test_handler_is_callable(self):
        """Handler is a callable function."""
        from mission_control.handlers import process_range_event

        assert callable(process_range_event)

    # ---------------------------------------------------------------------
    # Group name
    # ---------------------------------------------------------------------

    def test_uses_correct_group_name_format(self):
        """Handler uses range_event_group helper for group name."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 123,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            args, _ = mock_send.call_args
            assert args[0] == "range_status_123"

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self):
        """Handler works with minimal event fields."""
        from mission_control.handlers import process_range_event

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 6,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.async_to_sync") as mock_async_to_sync:
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send

            process_range_event(message)

            # Should have broadcast
            mock_send.assert_called_once()
