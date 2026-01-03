"""Channel group name utilities for Shifter platform.

These helpers provide consistent group naming for Django Channels
WebSocket layer (Mission Control browser connections).
"""

from __future__ import annotations


def range_event_group(range_id: int) -> str:
    """Get the channel group name for a specific range.

    Used for subscribing to status updates for a specific range.

    Args:
        range_id: The ID of the range.

    Returns:
        Channel group name in format "range_status_{range_id}".
    """
    return f"range_status_{range_id}"


def user_event_group(user_id: int) -> str:
    """Get the channel group name for a specific user.

    Used for subscribing to all events for a specific user.

    Args:
        user_id: The ID of the user.

    Returns:
        Channel group name in format "user_{user_id}".
    """
    return f"user_{user_id}"
