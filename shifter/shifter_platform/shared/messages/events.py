"""Event message contracts for Shifter platform pub/sub.

These Pydantic models define the data contracts for events published
by the Engine provisioner and consumed by CMS, Engine, and Mission Control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from shared.enums import InstanceStatus, RangeStatus

# Event type constants - Range
EVENT_TYPE_STATUS_UPDATED = "range.status.updated"
EVENT_TYPE_PROVISIONED = "range.provisioned"
EVENT_TYPE_DESTROYED = "range.destroyed"
EVENT_TYPE_CANCELLED = "range.cancelled"

# Event type constants - NGFW
EVENT_TYPE_NGFW_STATUS_UPDATED = "ngfw.status.updated"
EVENT_TYPE_NGFW_PROVISIONED = "ngfw.provisioned"
EVENT_TYPE_NGFW_DESTROYED = "ngfw.destroyed"


class BaseEvent(BaseModel):
    """Base class for all events.

    Provides common fields for event identification and tracing.
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
    """

    range_id: int
    user_id: int
    new_status: RangeStatus
    error_message: str | None = None


class RangeProvisionedEvent(BaseEvent):
    """Event published when a range is fully provisioned.

    Contains the complete list of provisioned instances with their details.
    """

    range_id: int
    user_id: int
    instances: list[dict[str, Any]]


class RangeDestroyedEvent(BaseEvent):
    """Event published when a range is fully destroyed."""

    range_id: int
    user_id: int


class RangeCancelledEvent(BaseEvent):
    """Event published when a range provisioning is cancelled."""

    range_id: int
    user_id: int


# =============================================================================
# NGFW Events
# =============================================================================


class NGFWStatusUpdatedEvent(BaseEvent):
    """Event published when an NGFW's status changes.

    Published by the provisioner during lifecycle transitions.
    Consumed by:
    - Engine: Updates NGFW model status
    - CMS: Updates NGFW model status
    - Mission Control: Pushes to browser WebSocket
    """

    ngfw_id: int  # Engine's NGFW.id
    cms_ngfw_id: int  # CMS's NGFW.id for correlation
    user_id: int
    new_status: InstanceStatus
    error_message: str | None = None


class NGFWProvisionedEvent(BaseEvent):
    """Event published when an NGFW is fully provisioned.

    Contains AWS resource details populated by the provisioner.
    """

    ngfw_id: int
    cms_ngfw_id: int
    user_id: int
    instance_id: str
    management_ip: str
    dataplane_ip: str
    service_name: str
    gwlb_arn: str
    target_group_arn: str


class NGFWDestroyedEvent(BaseEvent):
    """Event published when an NGFW is fully destroyed."""

    ngfw_id: int
    cms_ngfw_id: int
    user_id: int
