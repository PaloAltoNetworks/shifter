"""Tests for RangeStatusConsumer.range_status.

Tests the channel layer event handler for range status updates.

Contract being tested:
- Inputs: event (dict with range_id, new_status, error_message)
- Outputs: None (sends JSON message to WebSocket)
- Side effects: Sends status message to connected client
- Errors: None (best-effort send)
- Logging: None
"""

import json

import pytest

from shared.enums import RangeStatus


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusBasic:
    """Tests for RangeStatusConsumer.range_status basic functionality."""

    # -------------------------------------------------------------------------
    # Basic functionality - sends status updates
    # -------------------------------------------------------------------------

    async def test_sends_status_update_to_websocket(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() sends status update to WebSocket."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        consumer.send.assert_awaited_once()

    async def test_sends_json_formatted_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() sends JSON formatted message."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42
        consumer.group_name = "range_status_42"

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        text_data = call_args[1]["text_data"]
        # Should be valid JSON
        message = json.loads(text_data)
        assert isinstance(message, dict)


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusMessageFormat:
    """Tests for RangeStatusConsumer.range_status message format."""

    # -------------------------------------------------------------------------
    # Message format - correct structure
    # -------------------------------------------------------------------------

    async def test_message_contains_type_field(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() message contains type='status'."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "status"

    async def test_message_contains_range_id(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() message contains range_id from event."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["range_id"] == 42

    async def test_message_contains_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() message contains status from event.new_status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.READY.value

    async def test_message_contains_error_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() message contains error_message from event."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.FAILED.value,
            "error_message": "Provisioning failed: EC2 limit exceeded",
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] == "Provisioning failed: EC2 limit exceeded"

    async def test_message_has_exactly_four_fields(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() message has exactly type, range_id, status, error_message."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
            "error_message": None,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert set(message.keys()) == {"type", "range_id", "status", "error_message"}


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusValues:
    """Tests for RangeStatusConsumer.range_status with various status values."""

    # -------------------------------------------------------------------------
    # Status values - all enum values
    # -------------------------------------------------------------------------

    async def test_handles_ready_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles READY status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.READY.value

    async def test_handles_provisioning_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles PROVISIONING status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.PROVISIONING.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.PROVISIONING.value

    async def test_handles_destroying_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles DESTROYING status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.DESTROYING.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.DESTROYING.value

    async def test_handles_destroyed_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles DESTROYED status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.DESTROYED.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.DESTROYED.value

    async def test_handles_failed_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles FAILED status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.FAILED.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.FAILED.value

    async def test_handles_pending_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles PENDING status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.PENDING.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == RangeStatus.PENDING.value


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusErrorMessages:
    """Tests for RangeStatusConsumer.range_status error message handling."""

    # -------------------------------------------------------------------------
    # Error messages - various scenarios
    # -------------------------------------------------------------------------

    async def test_handles_none_error_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles None error_message."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value, "error_message": None}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] is None

    async def test_handles_missing_error_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles missing error_message (defaults to None via .get())."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] is None

    async def test_handles_empty_error_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles empty string error_message."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.FAILED.value, "error_message": ""}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] == ""

    async def test_handles_long_error_message(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles long error messages."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        long_error = "E" * 1000
        event = {"range_id": 42, "new_status": RangeStatus.FAILED.value, "error_message": long_error}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] == long_error

    async def test_handles_error_message_with_special_chars(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """range_status() handles error messages with special characters."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        special_error = 'Error: "Failed" <script>alert(1)</script> & stuff'
        event = {"range_id": 42, "new_status": RangeStatus.FAILED.value, "error_message": special_error}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] == special_error

    async def test_handles_error_message_with_newlines(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """range_status() handles error messages with newlines."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        multiline_error = "Error on line 1\nError on line 2\nError on line 3"
        event = {"range_id": 42, "new_status": RangeStatus.FAILED.value, "error_message": multiline_error}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["error_message"] == multiline_error


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusRangeId:
    """Tests for RangeStatusConsumer.range_status range_id handling."""

    # -------------------------------------------------------------------------
    # Range ID handling
    # -------------------------------------------------------------------------

    async def test_passes_through_event_range_id(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() uses range_id from event, not consumer.range_id."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 99  # Different from event

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        # Should use event range_id, not consumer.range_id
        assert message["range_id"] == 42

    async def test_handles_none_range_id_in_event(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles None range_id in event."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": None, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["range_id"] is None

    async def test_handles_missing_range_id_in_event(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles missing range_id in event."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["range_id"] is None

    async def test_handles_large_range_id(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles large range_id values."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        large_id = 999999999
        event = {"range_id": large_id, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["range_id"] == large_id


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusNewStatus:
    """Tests for RangeStatusConsumer.range_status new_status handling."""

    # -------------------------------------------------------------------------
    # New status handling
    # -------------------------------------------------------------------------

    async def test_handles_none_new_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles None new_status."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": None}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] is None

    async def test_handles_missing_new_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles missing new_status (defaults to None)."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] is None

    async def test_handles_unknown_status_string(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() passes through unknown status strings."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": "UNKNOWN_STATUS"}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["status"] == "UNKNOWN_STATUS"


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusExtraFields:
    """Tests for RangeStatusConsumer.range_status handling of extra event fields."""

    # -------------------------------------------------------------------------
    # Extra fields - ignored
    # -------------------------------------------------------------------------

    async def test_ignores_extra_fields_in_event(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() ignores extra fields in event."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
            "error_message": None,
            "extra_field": "should be ignored",
            "another_field": 12345,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        # Only expected fields present
        assert "extra_field" not in message
        assert "another_field" not in message

    async def test_does_not_include_event_type_in_message(
        self, range_status_consumer_factory, websocket_scope_range_status
    ):
        """range_status() does not pass event['type'] to message."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {
            "type": "range_status",  # Channel layer event type
            "range_id": 42,
            "new_status": RangeStatus.READY.value,
        }
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        # Message type should be "status", not "range_status"
        assert message["type"] == "status"


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusEmptyEvent:
    """Tests for RangeStatusConsumer.range_status with minimal/empty events."""

    # -------------------------------------------------------------------------
    # Minimal/empty events
    # -------------------------------------------------------------------------

    async def test_handles_empty_event(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles empty event dict."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        # All values should be None from .get() defaults
        assert message["type"] == "status"
        assert message["range_id"] is None
        assert message["status"] is None
        assert message["error_message"] is None

    async def test_handles_only_type_in_event(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles event with only type field."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"type": "range_status"}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        message = json.loads(call_args[1]["text_data"])
        assert message["type"] == "status"


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusJsonOutput:
    """Tests for RangeStatusConsumer.range_status JSON output format."""

    # -------------------------------------------------------------------------
    # JSON output validation
    # -------------------------------------------------------------------------

    async def test_output_is_valid_json(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() output is valid JSON."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        text_data = call_args[1]["text_data"]
        # Should not raise
        json.loads(text_data)

    async def test_uses_text_data_parameter(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() uses text_data parameter in send()."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        assert "text_data" in call_args[1]

    async def test_output_is_string_not_bytes(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() sends string, not bytes."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        event = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event)

        call_args = consumer.send.call_args
        text_data = call_args[1]["text_data"]
        assert isinstance(text_data, str)


@pytest.mark.asyncio
class TestRangeStatusConsumerRangeStatusMultipleCalls:
    """Tests for RangeStatusConsumer.range_status with multiple calls."""

    # -------------------------------------------------------------------------
    # Multiple calls - each is independent
    # -------------------------------------------------------------------------

    async def test_handles_multiple_status_updates(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles multiple sequential calls."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        # First update
        event1 = {"range_id": 42, "new_status": RangeStatus.PROVISIONING.value}
        await consumer.range_status(event1)

        # Second update
        event2 = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event2)

        assert consumer.send.await_count == 2

    async def test_each_call_sends_correct_status(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() sends correct status for each call."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        # First update
        event1 = {"range_id": 42, "new_status": RangeStatus.PROVISIONING.value}
        await consumer.range_status(event1)

        first_call = consumer.send.call_args_list[0]
        first_message = json.loads(first_call[1]["text_data"])
        assert first_message["status"] == RangeStatus.PROVISIONING.value

        # Second update
        event2 = {"range_id": 42, "new_status": RangeStatus.READY.value}
        await consumer.range_status(event2)

        second_call = consumer.send.call_args_list[1]
        second_message = json.loads(second_call[1]["text_data"])
        assert second_message["status"] == RangeStatus.READY.value

    async def test_handles_rapid_succession_updates(self, range_status_consumer_factory, websocket_scope_range_status):
        """range_status() handles rapid succession of updates."""
        consumer = range_status_consumer_factory(websocket_scope_range_status)
        consumer.range_id = 42

        statuses = [
            RangeStatus.PENDING.value,
            RangeStatus.PROVISIONING.value,
            RangeStatus.READY.value,
            RangeStatus.DESTROYING.value,
            RangeStatus.DESTROYED.value,
        ]

        for status in statuses:
            event = {"range_id": 42, "new_status": status}
            await consumer.range_status(event)

        assert consumer.send.await_count == 5
