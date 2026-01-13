"""Channel group name utilities. Re-exports from cyberscript.channels.groups."""

from cyberscript.channels.groups import (
    ngfw_event_group,
    range_event_group,
    user_event_group,
)

__all__ = [
    "ngfw_event_group",
    "range_event_group",
    "user_event_group",
]
