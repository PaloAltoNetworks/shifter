"""Wire-format event type constants (no Pydantic dependency).

These string literals are the persisted/external contract between the
provisioner publisher and platform consumers. Import this module from
runtimes that only need constants (e.g. the ECS provisioner image).
"""

# Event type constants - Range
EVENT_TYPE_STATUS_UPDATED = "range.status.updated"
EVENT_TYPE_PROVISIONED = "range.provisioned"
EVENT_TYPE_DESTROYED = "range.destroyed"
EVENT_TYPE_CANCELLED = "range.cancelled"

# Event type constants - NGFW
EVENT_TYPE_NGFW = "ngfw.event"

__all__ = [
    "EVENT_TYPE_CANCELLED",
    "EVENT_TYPE_DESTROYED",
    "EVENT_TYPE_NGFW",
    "EVENT_TYPE_PROVISIONED",
    "EVENT_TYPE_STATUS_UPDATED",
]
