"""Shared constants for Shifter platform.

Re-exports from cyberscript for Django compatibility.
"""

from cyberscript.constants import (
    USER_CANNOT_BE_NONE,
    USER_MUST_BE_SAVED,
)

__all__ = [
    "USER_CANNOT_BE_NONE",
    "USER_MUST_BE_SAVED",
]
