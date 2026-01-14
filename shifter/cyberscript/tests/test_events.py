"""Tests for shared.messages.events module."""

from datetime import UTC, datetime
from uuid import UUID

from cyberscript.enums import ResourceStatus


class TestResourceStatusUpdatedEvent:
    """Tests for ResourceStatusUpdatedEvent."""

    # ---------------------------------------------------------------------
    # Construction - required fields
    # ---------------------------------------------------------------------

    def test_creates_with_required_fields(self):
        """Event creates successfully with required fields."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
        )

        assert event.range_id == 1
        assert event.user_id == 42
        assert event.new_status == ResourceStatus.PROVISIONING
        assert event.error_message is None

    def test_auto_generates_event_id(self):
        """Event auto-generates UUID for event_id."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
        )

        assert isinstance(event.event_id, UUID)

    def test_auto_generates_timestamp(self):
        """Event auto-generates timestamp."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        before = datetime.now(UTC)
        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
        )
        after = datetime.now(UTC)

        assert before <= event.timestamp <= after

    def test_accepts_optional_error_message(self):
        """Event accepts error_message for failure events."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.FAILED,
            error_message="Subnet exhausted",
        )

        assert event.error_message == "Subnet exhausted"

    def test_accepts_correlation_id(self):
        """Event accepts optional correlation_id for tracing."""
        from uuid import uuid4

        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        correlation_id = uuid4()
        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
            correlation_id=correlation_id,
        )

        assert event.correlation_id == correlation_id

    # ---------------------------------------------------------------------
    # Serialization - JSON compatibility
    # ---------------------------------------------------------------------

    def test_serializes_to_dict(self):
        """Event serializes to dictionary."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
        )

        data = event.model_dump()

        assert data["range_id"] == 1
        assert data["user_id"] == 42
        assert data["new_status"] == "provisioning"

    def test_serializes_to_json(self):
        """Event serializes to JSON string."""
        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event = ResourceStatusUpdatedEvent(
            range_id=1,
            user_id=42,
            new_status=ResourceStatus.PROVISIONING,
        )

        json_str = event.model_dump_json()

        assert '"range_id":1' in json_str
        assert '"new_status":"provisioning"' in json_str

    def test_deserializes_from_dict(self):
        """Event deserializes from dictionary."""
        from uuid import uuid4

        from cyberscript.messages.events import ResourceStatusUpdatedEvent

        event_id = uuid4()
        timestamp = datetime.now(UTC)
        data = {
            "event_id": str(event_id),
            "timestamp": timestamp.isoformat(),
            "range_id": 1,
            "user_id": 42,
            "new_status": "provisioning",
        }

        event = ResourceStatusUpdatedEvent.model_validate(data)

        assert event.event_id == event_id
        assert event.range_id == 1


class TestRangeProvisionedEvent:
    """Tests for RangeProvisionedEvent."""

    def test_creates_with_instances(self):
        """Event stores provisioned instance details."""
        from cyberscript.messages.events import RangeProvisionedEvent

        instances = [
            {"uuid": "abc-123", "role": "attacker", "private_ip": "10.0.0.5"},
            {"uuid": "def-456", "role": "victim", "private_ip": "10.0.0.6"},
        ]

        event = RangeProvisionedEvent(
            range_id=1,
            user_id=42,
            instances=instances,
        )

        assert event.range_id == 1
        assert event.user_id == 42
        assert len(event.instances) == 2
        assert event.instances[0]["role"] == "attacker"

    def test_serializes_instances(self):
        """Event correctly serializes instance list."""
        from cyberscript.messages.events import RangeProvisionedEvent

        instances = [{"uuid": "abc-123", "role": "attacker"}]
        event = RangeProvisionedEvent(
            range_id=1,
            user_id=42,
            instances=instances,
        )

        data = event.model_dump()

        assert data["instances"] == instances


class TestRangeDestroyedEvent:
    """Tests for RangeDestroyedEvent."""

    def test_creates_with_range_id(self):
        """Event creates with range_id."""
        from cyberscript.messages.events import RangeDestroyedEvent

        event = RangeDestroyedEvent(range_id=1, user_id=42)

        assert event.range_id == 1
        assert event.user_id == 42


class TestRangeCancelledEvent:
    """Tests for RangeCancelledEvent."""

    def test_creates_with_range_id(self):
        """Event creates with range_id."""
        from cyberscript.messages.events import RangeCancelledEvent

        event = RangeCancelledEvent(range_id=1, user_id=42)

        assert event.range_id == 1
        assert event.user_id == 42


class TestEventType:
    """Tests for EVENT_TYPE constants."""

    def test_event_types_defined(self):
        """All event types have string constants."""
        from cyberscript.messages import events

        assert events.EVENT_TYPE_STATUS_UPDATED == "range.status.updated"
        assert events.EVENT_TYPE_PROVISIONED == "range.provisioned"
        assert events.EVENT_TYPE_DESTROYED == "range.destroyed"
        assert events.EVENT_TYPE_CANCELLED == "range.cancelled"
