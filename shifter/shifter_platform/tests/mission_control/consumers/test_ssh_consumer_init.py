"""Tests for SSHConsumer.__init__.

Tests the initialization of SSHConsumer, verifying that instance
state is properly initialized.

Contract being tested:
- Inputs: args and kwargs passed to parent AsyncWebsocketConsumer
- Outputs: None (constructor)
- Side effects: Initializes instance_uuid, range_id, ssh_conn, _read_task to None
- Errors: None (constructor relies on parent)
- Logging: None
"""

from mission_control.consumers import SSHConsumer


class TestSSHConsumerInit:
    """Tests for SSHConsumer.__init__."""

    # -------------------------------------------------------------------------
    # Happy path - initialization succeeds
    # -------------------------------------------------------------------------

    def test_initializes_instance_uuid_to_none(self):
        """Constructor initializes instance_uuid to None."""
        consumer = SSHConsumer()

        assert consumer.instance_uuid is None

    def test_initializes_range_id_to_none(self):
        """Constructor initializes range_id to None."""
        consumer = SSHConsumer()

        assert consumer.range_id is None

    def test_initializes_ssh_conn_to_none(self):
        """Constructor initializes ssh_conn to None."""
        consumer = SSHConsumer()

        assert consumer.ssh_conn is None

    def test_initializes_read_task_to_none(self):
        """Constructor initializes _read_task to None."""
        consumer = SSHConsumer()

        assert consumer._read_task is None

    def test_inherits_from_async_websocket_consumer(self):
        """Constructor properly inherits from AsyncWebsocketConsumer."""
        from channels.generic.websocket import AsyncWebsocketConsumer

        consumer = SSHConsumer()

        assert isinstance(consumer, AsyncWebsocketConsumer)

    # -------------------------------------------------------------------------
    # Multiple instantiation - each instance is independent
    # -------------------------------------------------------------------------

    def test_multiple_instances_have_independent_state(self):
        """Each SSHConsumer instance has independent state."""
        consumer1 = SSHConsumer()
        consumer2 = SSHConsumer()

        # Modify consumer1 state
        consumer1.instance_uuid = "uuid-1"
        consumer1.range_id = 1

        # consumer2 should be unaffected
        assert consumer2.instance_uuid is None
        assert consumer2.range_id is None

    # -------------------------------------------------------------------------
    # Type annotations - verify correct types
    # -------------------------------------------------------------------------

    def test_instance_uuid_type_annotation(self):
        """instance_uuid has correct type annotation (str | None)."""
        consumer = SSHConsumer()

        # Should accept string
        consumer.instance_uuid = "test-uuid"
        assert consumer.instance_uuid == "test-uuid"

        # Should accept None
        consumer.instance_uuid = None
        assert consumer.instance_uuid is None

    def test_range_id_type_annotation(self):
        """range_id has correct type annotation (int | None)."""
        consumer = SSHConsumer()

        # Should accept int
        consumer.range_id = 42
        assert consumer.range_id == 42

        # Should accept None
        consumer.range_id = None
        assert consumer.range_id is None
