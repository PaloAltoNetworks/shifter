"""Channel group name utilities for Shifter platform.

These helpers provide consistent group naming for Django Channels
WebSocket layer (Mission Control browser connections).
"""

from __future__ import annotations


def range_event_group(request_id: str) -> str:
    """Get the channel group name for a specific range.

    Used for subscribing to status updates for a specific range.
    Uses request_id (UUID) for consistency with NGFW pattern.

    Args:
        request_id: The UUID of the request (as string).

    Returns:
        Channel group name in format "range_status_{request_id}".
    """
    return f"range_status_{request_id}"


def user_event_group(user_id: int) -> str:
    """Get the channel group name for a specific user.

    Used for subscribing to all events for a specific user.

    Args:
        user_id: The ID of the user.

    Returns:
        Channel group name in format "user_{user_id}".
    """
    return f"user_{user_id}"


def ngfw_event_group(app_id: str) -> str:
    """Get the channel group name for a specific NGFW app.

    Used for subscribing to status updates for a specific NGFW.

    Args:
        app_id: The UUID of the NGFW App (CMS App.id).

    Returns:
        Channel group name in format "ngfw_status_{app_id}".
    """
    return f"ngfw_status_{app_id}"
