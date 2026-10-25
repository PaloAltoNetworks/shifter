"""Read public runtime values inside a guest action (standard library only).

The worker requests typed references in ``GuestAction.runtime_values``. The host
resolves them after realization and supplies base64-encoded JSON to that action.
Never interpolate these values as shell source; read them as data in the guest.
"""

from __future__ import annotations

import base64
import json
import os

RUNTIME_VALUES_ENV = "SHIFTER_RUNTIME_VALUES_B64"
MAX_RUNTIME_VALUES_BYTES = 32_768


def read_runtime_values() -> dict[str, str]:
    """Return this action's host-provided values, rejecting absent/bad transport."""
    try:
        encoded = os.environ[RUNTIME_VALUES_ENV]
        if len(encoded) > 4 * ((MAX_RUNTIME_VALUES_BYTES + 2) // 3):
            raise ValueError
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_RUNTIME_VALUES_BYTES:
            raise ValueError
        values = json.loads(raw)
        if not isinstance(values, dict) or len(values) > 64:
            raise ValueError
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()):
            raise ValueError
        return values
    except (KeyError, ValueError, UnicodeError, RecursionError):
        raise ValueError("Guest runtime values are unavailable or invalid") from None
