"""Channel group name utilities for Shifter platform.

These helpers provide consistent group naming for Django Channels
WebSocket layer (Mission Control browser connections).
"""

from __future__ import annotations

import hashlib


def range_event_group(request_id: str | int) -> str:
    """Get the channel group name for a specific range.

    Used for subscribing to status updates for a specific range.
    Uses request_id (UUID) for consistency with NGFW pattern.

    Args:
        request_id: The UUID of the request (as string) or range_id (as int).

    Returns:
        Channel group name in format "range_status_{request_id}".

    Examples:
        >>> range_event_group("abc-123-def")
        'range_status_abc-123-def'
        >>> range_event_group(123)
        'range_status_123'
    """
    return f"range_status_{request_id}"


def user_event_group(user_id: int) -> str:
    """Get the channel group name for a specific user.

    Used for subscribing to all events for a specific user.

    Args:
        user_id: The ID of the user.

    Returns:
        Channel group name in format "user_{user_id}".

    Examples:
        >>> user_event_group(42)
        'user_42'
    """
    return f"user_{user_id}"


def ngfw_event_group(app_id: str) -> str:
    """Get the channel group name for a specific NGFW app.

    Used for subscribing to status updates for a specific NGFW.

    Args:
        app_id: The UUID of the NGFW App (CMS App.id).

    Returns:
        Channel group name in format "ngfw_status_{app_id}".

    Examples:
        >>> ngfw_event_group("abc-123-def")
        'ngfw_status_abc-123-def'
    """
    return f"ngfw_status_{app_id}"


def notification_user_topic_group(user_id: int, topic: str) -> str:
    """Get the channel group name for one user's logical notification topic.

    Logical notification topics are user-facing contracts and may contain
    separators such as ``:``. Channels group names are transport details with
    stricter character and length limits, so this helper keeps the raw topic out
    of the group name and uses a stable digest instead.
    """
    digest = hashlib.sha256(str(topic).encode("utf-8")).hexdigest()[:32]
    return f"notify_u{int(user_id)}_{digest}"
