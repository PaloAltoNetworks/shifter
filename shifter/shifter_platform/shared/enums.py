"""Shared enums for Shifter platform.

These enums define shared values used across CMS, Engine, and Provisioner.
They are string enums for JSON serialization compatibility.
"""

from __future__ import annotations

from enum import Enum


class RangeStatus(str, Enum):
    """Range lifecycle status.

    Used by both CMS (RangeInstance.status) and Engine (Range.status)
    to track range state throughout its lifecycle.
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
ACTIVE_STATUSES: set[RangeStatus] = {
    RangeStatus.PENDING,
    RangeStatus.PROVISIONING,
    RangeStatus.READY,
    RangeStatus.PAUSED,
    RangeStatus.RESUMING,
    RangeStatus.DESTROYING,
}

TERMINAL_STATUSES: set[RangeStatus] = {
    RangeStatus.DESTROYED,
    RangeStatus.FAILED,
}

CANCELLABLE_STATUSES: set[RangeStatus] = {
    RangeStatus.PENDING,
    RangeStatus.PROVISIONING,
}
