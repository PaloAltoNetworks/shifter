"""Shared environment-variable parsing helpers.

Leaf module: no dependencies on sibling ``config`` submodules. Used across
the crypto/provider, range, GDC, GCE, NGFW, and AWS-Polaris-agent domains to
parse env vars consistently (ints, bools, CSV lists, and "first non-empty"
fallback chains).
"""

import os
from typing import Any


def _get_int_env(name: str, default: int) -> int:
    """Return an int env var, or ``default`` if unset/blank."""
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _get_bool_env(name: str, default: bool) -> bool:
    """Return a boolean env var, treating 1/true/yes/on as true."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def _parse_csv_env(value: str) -> tuple[str, ...]:
    """Split a comma-separated env value into trimmed, non-empty items."""
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _first_non_empty_string(*values: Any) -> str:
    """Return the first non-empty value as a normalized string."""
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        elif value not in (None, ""):
            normalized = str(value).strip()
            if normalized:
                return normalized
    return ""
