"""Shared contracts and schemas for Shifter platform.

This package contains Pydantic schemas that define data contracts
between CMS, Engine, and Provisioner components.

Submodules:
    - schemas: Pydantic models for data contracts (RangeSpec, SubnetSpec, etc.)
    - messages: Event message types for pub/sub communication
    - channels: WebSocket channel group name utilities
    - enums: Shared enumerations (ResourceStatus, etc.)
    - exceptions: Shared exception types
"""

from .enums import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    TERMINAL_STATUSES,
    RequestType,
    ResourceStatus,
    ResourceType,
    WebSocketCloseCode,
)
from .exceptions import (
    AssetError,
    CMSError,
    ProvisioningError,
    ValidationError,
)

__all__ = [
    # Enums
    "ACTIVE_STATUSES",
    "CANCELLABLE_STATUSES",
    "TERMINAL_STATUSES",
    "RequestType",
    "ResourceStatus",
    "ResourceType",
    "WebSocketCloseCode",
    # Exceptions
    "AssetError",
    "CMSError",
    "ProvisioningError",
    "ValidationError",
]
