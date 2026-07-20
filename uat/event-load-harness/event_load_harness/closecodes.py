"""Client-side mirror of the portal's websocket close codes.

Authoritative source: ``shifter/cyberscript/enums.py`` ``WebSocketCloseCode``.
The harness mirrors these values rather than importing the Django application so
it stays a standalone client (runnable without the app installed and portable
across deployment platforms). ``tests/test_closecodes.py`` guards the mirror
against drift; update both together if the app enum changes.
"""

from __future__ import annotations

from enum import IntEnum


class CloseCode(IntEnum):
    """Websocket close codes used by the Shifter portal consumers.

    Mirror of ``cyberscript.enums.WebSocketCloseCode``. Standard codes
    (1000-1015) are RFC 6455; application codes (4000-4999) are Shifter-specific.
    """

    NORMAL = 1000
    NOT_AUTHENTICATED = 4001
    PERMISSION_DENIED = 4003
    NOT_FOUND = 4004
    INVALID_REQUEST = 4005
    SERVER_ERROR = 4500
    SSH_CONNECTION_FAILED = 4502
    SERVICE_UNAVAILABLE = 4503


def close_code_label(code: int | None) -> str:
    """Return a stable, low-cardinality label for a websocket close ``code``.

    Known codes map to their enum name. ``None`` (no close frame observed) maps
    to ``"NONE"``; any other integer collapses to ``"OTHER"`` so error
    histograms never explode in cardinality or echo an unexpected raw value.
    """
    if code is None:
        return "NONE"
    try:
        return CloseCode(code).name
    except ValueError:
        return "OTHER"
