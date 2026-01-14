"""Message contracts for Shifter platform pub/sub.

This module provides event message types for communication between
CMS, Engine, and Provisioner components.
"""

from .events import (
    EVENT_TYPE_CANCELLED,
    EVENT_TYPE_DESTROYED,
    EVENT_TYPE_NGFW,
    EVENT_TYPE_PROVISIONED,
    EVENT_TYPE_STATUS_UPDATED,
    BaseEvent,
    NGFWEvent,
    RangeCancelledEvent,
    RangeDestroyedEvent,
    RangeProvisionedEvent,
    RangeStatusUpdatedEvent,
    # Backward compatibility alias
    ResourceStatusUpdatedEvent,
)

__all__ = [
    # Event types
    "EVENT_TYPE_CANCELLED",
    "EVENT_TYPE_DESTROYED",
    "EVENT_TYPE_NGFW",
    "EVENT_TYPE_PROVISIONED",
    "EVENT_TYPE_STATUS_UPDATED",
    # Event classes
    "BaseEvent",
    "NGFWEvent",
    "RangeCancelledEvent",
    "RangeDestroyedEvent",
    "RangeProvisionedEvent",
    "RangeStatusUpdatedEvent",
    # Backward compatibility
    "ResourceStatusUpdatedEvent",
]
