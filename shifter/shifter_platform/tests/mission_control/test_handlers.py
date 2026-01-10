"""Tests for Mission Control handlers."""

import json
import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from shared.enums import ResourceStatus

# Test UUID for request_id
TEST_REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.mark.django_db
class TestProcessEvent:
    """Tests for process_event dispatcher."""

    def test_routes_range_events_to_range_handler(self):
        """Dispatcher routes range.* events to process_range_event."""
        from mission_control.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.process_range_event") as mock_range_handler:
            process_event(message)
            mock_range_handler.assert_called_once_with(message)

    def test_routes_ngfw_events_to_ngfw_handler(self):
        """Dispatcher routes ngfw.* events to process_ngfw_event."""
        from mission_control.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "ngfw.status.updated",
                    "ngfw_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("mission_control.handlers.process_ngfw_event") as mock_ngfw_handler:
            process_event(message)
            mock_ngfw_handler.assert_called_once_with(message)

    def test_ignores_unknown_event_types(self):
        """Dispatcher ignores events with unknown event_type prefix."""
        from mission_control.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "unknown.event",
                    "some_id": 1,
                }
            )
        }

        with (
            patch("mission_control.handlers.process_range_event") as mock_range_handler,
            patch("mission_control.handlers.process_ngfw_event") as mock_ngfw_handler,
            patch("mission_control.handlers.logger") as mock_logger,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()
            mock_logger.debug.assert_called_once()
            assert "unknown" in str(mock_logger.debug.call_args)

    def test_handles_missing_event_type(self, caplog):
        """Dispatcher handles messages without event_type gracefully."""
        from mission_control.handlers import process_event

        message = {"Message": json.dumps({"range_id": 1})}

        with (
            caplog.at_level(logging.DEBUG, logger="mission_control.handlers"),
            patch("mission_control.handlers.process_range_event") as mock_range_handler,
            patch("mission_control.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()

    def test_dispatcher_is_callable(self):
        """Dispatcher is a callable function."""
        from mission_control.handlers import process_event

        assert callable(process_event)


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

    @pytest.fixture
    def mock_range(self):
        """Create a mock Range object with request FK."""
        mock_request = MagicMock()
        mock_request.request_id = TEST_REQUEST_ID

        mock_range_obj = MagicMock()
        mock_range_obj.request = mock_request

        return mock_range_obj

    # ---------------------------------------------------------------------
    # Happy path - broadcast to channel layer
    # ---------------------------------------------------------------------

    def test_broadcasts_status_update_to_channel_layer(self, mock_range):
        """Handler broadcasts status update to Django Channels group."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

            process_range_event(message)

            # Verify Range was looked up
            mock_range_model.objects.select_related.assert_called_once_with("request")

            # Verify async_to_sync was called with group_send
            mock_async_to_sync.assert_called_once()

            # Verify the sync wrapper was called with correct args
            mock_send.assert_called_once()
            args, _ = mock_send.call_args

            # Verify group name uses request_id
            assert args[0] == f"range_status_{TEST_REQUEST_ID}"

            # Verify message content uses request_id
            sent_message = args[1]
            assert sent_message["type"] == "range.status"
            assert sent_message["request_id"] == str(TEST_REQUEST_ID)
            assert sent_message["new_status"] == ResourceStatus.PROVISIONING.value

    def test_broadcasts_error_message_when_present(self, mock_range):
        """Handler includes error_message in broadcast when present."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 2,
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": 42,
                    "error_message": "Subnet exhausted",
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

            process_range_event(message)

            # Verify error_message included
            args, _ = mock_send.call_args
            sent_message = args[1]
            assert sent_message["error_message"] == "Subnet exhausted"

    def test_broadcasts_null_error_message_when_not_present(self, mock_range):
        """Handler includes null error_message when not in event."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 3,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

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

    def test_logs_info_on_successful_broadcast(self, mock_range):
        """Handler logs INFO when broadcast succeeds."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 5,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("mission_control.handlers.logger") as mock_logger,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

            process_range_event(message)

        # Verify logger.info was called with expected content
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "MC broadcast to group" in call_args[0]
        assert f"range_status_{TEST_REQUEST_ID}" in call_args[1]
        assert call_args[2] == str(TEST_REQUEST_ID)  # request_id

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

    def test_uses_correct_group_name_format(self, mock_range):
        """Handler uses range_event_group helper for group name."""
        from mission_control.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 123,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

            process_range_event(message)

            args, _ = mock_send.call_args
            assert args[0] == f"range_status_{TEST_REQUEST_ID}"

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self, mock_range):
        """Handler works with minimal event fields."""
        from mission_control.handlers import process_range_event

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 6,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with (
            patch("mission_control.handlers.async_to_sync") as mock_async_to_sync,
            patch("engine.models.Range") as mock_range_model,
        ):
            mock_send = MagicMock()
            mock_async_to_sync.return_value = mock_send
            mock_range_model.objects.select_related.return_value.get.return_value = mock_range

            process_range_event(message)

            # Should have broadcast
            mock_send.assert_called_once()
