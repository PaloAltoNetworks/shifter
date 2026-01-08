"""Shared enums for Shifter platform.

These enums define shared values used across CMS, Engine, and Provisioner.
They are string enums for JSON serialization compatibility.
"""

from __future__ import annotations

from enum import Enum


class ResourceType(str, Enum):
    """Top-level resource categories managed by the engine.

    RANGE and NGFW are independent resource types with separate lifecycles.
    Used by the provisioner to dispatch to the correct setup/teardown logic.
    """

    RANGE = "range"
    NGFW = "ngfw"


class RequestType(str, Enum):
    """Type of provisioning request.

    Used by Request models to categorize what is being requested.
    """

    NGFW = "ngfw"


class ResourceStatus(str, Enum):
    """Resource lifecycle status.

    Used by both CMS (Resource.status) and Engine (Resource.status)
    to track resource state throughout its lifecycle.
    """

    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    PAUSED = "paused"
    RESUMING = "resuming"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "failed"


# Status groupings for lifecycle queries
ACTIVE_STATUSES: set[ResourceStatus] = {
    ResourceStatus.PENDING,
    ResourceStatus.PROVISIONING,
    ResourceStatus.READY,
    ResourceStatus.PAUSED,
    ResourceStatus.RESUMING,
    ResourceStatus.DESTROYING,
}

TERMINAL_STATUSES: set[ResourceStatus] = {
    ResourceStatus.DESTROYED,
    ResourceStatus.FAILED,
}

CANCELLABLE_STATUSES: set[ResourceStatus] = {
    ResourceStatus.PENDING,
    ResourceStatus.PROVISIONING,
}


class WebSocketCloseCode(int, Enum):
    """WebSocket close codes for Shifter consumers.

    Standard codes (1000-1015) are defined by RFC 6455.
    Application codes (4000-4999) are for application-specific use.
    """

    # Standard codes
    NORMAL = 1000

    # Application codes - Authentication/Authorization
    NOT_AUTHENTICATED = 4001
    PERMISSION_DENIED = 4003
    NOT_FOUND = 4004
    INVALID_REQUEST = 4005

    # Application codes - Server errors
    SERVER_ERROR = 4500
    SSH_CONNECTION_FAILED = 4502
    SERVICE_UNAVAILABLE = 4503
