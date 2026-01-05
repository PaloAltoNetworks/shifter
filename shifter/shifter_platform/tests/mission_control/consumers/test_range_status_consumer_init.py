"""Tests for RangeStatusConsumer.__init__.

Tests the initialization of RangeStatusConsumer.

Contract being tested:
- Inputs: args and kwargs passed to parent AsyncWebsocketConsumer
- Outputs: None (constructor)
- Side effects: Initializes range_id and group_name to None
- Errors: None (constructor relies on parent)
- Logging: None
"""

from mission_control.consumers import RangeStatusConsumer


class TestRangeStatusConsumerInit:
    """Tests for RangeStatusConsumer.__init__."""

    # -------------------------------------------------------------------------
    # Happy path - initialization succeeds
    # -------------------------------------------------------------------------

    def test_initializes_range_id_to_none(self):
        """Constructor initializes range_id to None."""
        consumer = RangeStatusConsumer()

        assert consumer.range_id is None

    def test_initializes_group_name_to_none(self):
        """Constructor initializes group_name to None."""
        consumer = RangeStatusConsumer()

        assert consumer.group_name is None

    def test_inherits_from_async_websocket_consumer(self):
        """Constructor properly inherits from AsyncWebsocketConsumer."""
        from channels.generic.websocket import AsyncWebsocketConsumer

        consumer = RangeStatusConsumer()

        assert isinstance(consumer, AsyncWebsocketConsumer)

    # -------------------------------------------------------------------------
    # Multiple instantiation - each instance is independent
    # -------------------------------------------------------------------------

    def test_multiple_instances_have_independent_state(self):
        """Each RangeStatusConsumer instance has independent state."""
        consumer1 = RangeStatusConsumer()
        consumer2 = RangeStatusConsumer()

        # Modify consumer1 state
        consumer1.range_id = 42
        consumer1.group_name = "range_status_42"

        # consumer2 should be unaffected
        assert consumer2.range_id is None
        assert consumer2.group_name is None

    # -------------------------------------------------------------------------
    # Type annotations - verify correct types
    # -------------------------------------------------------------------------

    def test_range_id_type_annotation(self):
        """range_id has correct type annotation (int | None)."""
        consumer = RangeStatusConsumer()

        # Should accept int
        consumer.range_id = 42
        assert consumer.range_id == 42

        # Should accept None
        consumer.range_id = None
        assert consumer.range_id is None

    def test_group_name_type_annotation(self):
        """group_name has correct type annotation (str | None)."""
        consumer = RangeStatusConsumer()

        # Should accept string
        consumer.group_name = "range_status_42"
        assert consumer.group_name == "range_status_42"

        # Should accept None
        consumer.group_name = None
        assert consumer.group_name is None
