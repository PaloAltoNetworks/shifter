"""Shared enums for Shifter platform.

Re-exports DSL-owned enums from cyberscript for Django compatibility, and
defines platform-native shared contracts (e.g. ``RangeSource``) that are not
part of the scenario DSL.
"""

from enum import StrEnum

from cyberscript.enums import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    TERMINAL_STATUSES,
    RequestType,
    ResourceStatus,
    ResourceType,
    WebSocketCloseCode,
)


class RangeSource(StrEnum):
    """Provenance of a CMS range: which product path created it.

    Platform range provenance (not a scenario-DSL contract), so it lives in
    shared natively rather than in ``cyberscript``. Server-derived only — never
    supplied by user request bodies or query params. Used by CMS range admission
    to allow a user to hold one active range per source.
    """

    MISSION_CONTROL = "mission_control"
    CTF = "ctf"


__all__ = [
    "ACTIVE_STATUSES",
    "CANCELLABLE_STATUSES",
    "TERMINAL_STATUSES",
    "RangeSource",
    "RequestType",
    "ResourceStatus",
    "ResourceType",
    "WebSocketCloseCode",
]
