"""Shared enums for Shifter platform.

Re-exports from cyberscript for Django compatibility.
"""

from cyberscript.enums import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    TERMINAL_STATUSES,
    RequestType,
    ResourceStatus,
    ResourceType,
    WebSocketCloseCode,
)

__all__ = [
    "ACTIVE_STATUSES",
    "CANCELLABLE_STATUSES",
    "TERMINAL_STATUSES",
    "RequestType",
    "ResourceStatus",
    "ResourceType",
    "WebSocketCloseCode",
]
