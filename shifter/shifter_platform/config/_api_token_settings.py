"""API token policy settings (PLAT-102).

Extracted from ``config.settings`` to keep that module under Sonar S104's
500-line cap — the same split pattern the other ``config/_*.py`` modules use.
``config.settings`` re-exports these via ``from config._api_token_settings import *``.
"""

from __future__ import annotations

import os

__all__ = ["API_TOKEN_LAST_USED_COALESCE_SECONDS", "API_TOKEN_MAX_TTL_DAYS"]


def _env_int(name: str, default: int) -> int:
    """Parse an integer env var, failing loud on a non-integer value."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


# Coalesce ApiToken.last_used_at writes to at most once per this many seconds,
# so high-frequency token traffic does not amplify into a write per request.
API_TOKEN_LAST_USED_COALESCE_SECONDS = _env_int("API_TOKEN_LAST_USED_COALESCE_SECONDS", 300)
# Advisory maximum token lifetime (days) for the admin token-creation UI.
API_TOKEN_MAX_TTL_DAYS = _env_int("API_TOKEN_MAX_TTL_DAYS", 365)
