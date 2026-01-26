"""Channel utilities for Shifter platform WebSocket layer.

This module provides channel group naming helpers for Django Channels.
"""

from .groups import ngfw_event_group, range_event_group, user_event_group

__all__ = [
    "ngfw_event_group",
    "range_event_group",
    "user_event_group",
]
