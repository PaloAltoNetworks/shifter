"""Named validator registry, plus the built-in validator functions.

Validators are Python callables with the signature:
    (submitted_flag: str, params: dict[str, Any]) -> bool
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Type alias for validator functions
ValidatorFunc = Callable[[str, dict[str, Any]], bool]

# Registry of named validators
_VALIDATORS: dict[str, ValidatorFunc] = {}


def register_validator(name: str, func: ValidatorFunc) -> None:
    """Register a named validator function."""
    _VALIDATORS[name] = func


def get_validator(name: str) -> ValidatorFunc | None:
    """Get a registered validator by name, or None if unknown."""
    return _VALIDATORS.get(name)


def list_validators() -> list[str]:
    """Sorted list of registered validator names."""
    return sorted(_VALIDATORS.keys())


# ---------------------------------------------------------------------------
# Built-in validators
# ---------------------------------------------------------------------------


def _always_true(submitted_flag: str, params: dict[str, Any]) -> bool:
    """Always returns True. Useful for testing."""
    return True


def _contains_substring(submitted_flag: str, params: dict[str, Any]) -> bool:
    """Check if the submitted flag contains a configured substring.

    Params:
        substring (str): The substring to search for.
        case_sensitive (bool): Whether comparison is case-sensitive (default True).
    """
    substring = params.get("substring", "")
    if not substring:
        return False
    case_sensitive = params.get("case_sensitive", True)
    if case_sensitive:
        return substring in submitted_flag
    return substring.lower() in submitted_flag.lower()


# Register built-in validators
register_validator("always_true", _always_true)
register_validator("contains_substring", _contains_substring)
