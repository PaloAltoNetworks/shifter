"""Event message contracts for Shifter platform pub/sub.

These Pydantic models define the data contracts for events published
by the Engine provisioner and consumed by CMS, Engine, and Mission Control.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from ..enums import ResourceStatus

logger = logging.getLogger(__name__)

# Event type constants - Range
EVENT_TYPE_STATUS_UPDATED = "range.status.updated"
EVENT_TYPE_PROVISIONED = "range.provisioned"
EVENT_TYPE_DESTROYED = "range.destroyed"
EVENT_TYPE_CANCELLED = "range.cancelled"

# Event type constants - NGFW
EVENT_TYPE_NGFW = "ngfw.event"


class BaseEvent(BaseModel):
    """Base class for all events.

    Provides common fields for event identification and tracing.

    Attributes:
        event_id: Unique identifier for this event instance.
        timestamp: When the event was created (UTC).
        correlation_id: Optional ID for tracing related events.
    """

    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID | None = None


class RangeStatusUpdatedEvent(BaseEvent):
    """Event published when a range's status changes.

    Published by the provisioner during lifecycle transitions.
    Consumed by:
    - Engine: Updates Range model status
    - CMS: Updates RangeInstance model status
    - Mission Control: Pushes to browser WebSocket

    Attributes:
        request_id: Primary correlation key (UUID).
        range_id: Engine database ID for lookup.
        user_id: Owner of the range.
        new_status: The new status value.
        error_message: Optional error details for failure states.
    """

    request_id: UUID | None = None  # Primary correlation key
    range_id: int  # Engine uses this for DB lookup
    user_id: int
    new_status: ResourceStatus
    error_message: str | None = None

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


# Backward compatibility alias
ResourceStatusUpdatedEvent = RangeStatusUpdatedEvent


class RangeProvisionedEvent(BaseEvent):
    """Event published when a range is fully provisioned.

    Contains the complete list of provisioned instances with their details.

    Attributes:
        request_id: Primary correlation key (UUID).
        range_id: Engine database ID.
        user_id: Owner of the range.
        instances: List of provisioned instance details.
        subnet_id: AWS subnet ID (optional).
        subnet_cidr: Subnet CIDR block (optional).
        pulumi_stack: Name of the Pulumi stack (optional).
    """

    request_id: UUID | None = None  # Primary correlation key
    range_id: int
    user_id: int
    instances: list[dict[str, Any]]
    subnet_id: str | None = None
    subnet_cidr: str | None = None
    pulumi_stack: str | None = None

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


class RangeDestroyedEvent(BaseEvent):
    """Event published when a range is fully destroyed.

    Attributes:
        request_id: Primary correlation key (UUID).
        range_id: Engine database ID.
        user_id: Owner of the range.
    """

    request_id: UUID | None = None  # Primary correlation key
    range_id: int
    user_id: int

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


class RangeCancelledEvent(BaseEvent):
    """Event published when a range provisioning is cancelled.

    Attributes:
        request_id: Primary correlation key (UUID).
        range_id: Engine database ID.
        user_id: Owner of the range.
    """

    request_id: UUID | None = None  # Primary correlation key
    range_id: int
    user_id: int

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


# =============================================================================
# NGFW Events
# =============================================================================


class NGFWEvent(BaseEvent):
    """Unified event for NGFW lifecycle changes.

    Published by the provisioner during NGFW lifecycle transitions.
    Consumed by:
    - Engine: Updates NGFW/Instantiation status
    - CMS: Updates NGFW model status
    - Mission Control: Pushes to browser WebSocket

    The state dict contains context-specific data such as:
    - Provisioned: instance_id, management_ip, dataplane_ip, service_name, etc.
    - Destroyed: (typically empty)
    - Failed: error_message

    Attributes:
        request_id: Provisioning request UUID.
        instance_id: CMS Instance UUID for correlation.
        app_id: CMS App UUID for correlation.
        status: New resource status (optional).
        state: Context-specific state data (optional).
    """

    request_id: UUID
    instance_id: UUID
    app_id: UUID
    status: ResourceStatus | None = None
    state: dict[str, Any] | None = None
