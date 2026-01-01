"""Management service interface.

Platform administration for Shifter platform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def log_activity(action: str, user: User, **metadata: Any) -> None:
    """Audit logging."""
    raise NotImplementedError
