"""Engine service interface.

Infrastructure lifecycle for Shifter platform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def create_range(range_config: dict[str, Any]) -> int:
    """Provision infrastructure for range.

    Args:
        range_config: Fully resolved configuration dict containing
            scenario, agent details, credentials, and instance specs.

    Returns:
        range_id: The ID of the created range.
    """
    raise NotImplementedError


def destroy_range(range_id: int) -> None:
    """Tear down range infrastructure."""
    raise NotImplementedError


def cancel_range(range_id: int) -> None:
    """Cancel in-progress provisioning."""
    raise NotImplementedError


def get_range_status(range_id: int) -> dict[str, Any]:
    """Get current state, progress, instances.

    Returns:
        Dict with keys: status, progress, message, instances
    """
    raise NotImplementedError


def pause_range(range_id: int) -> None:
    """Pause range instances."""
    raise NotImplementedError


def resume_range(range_id: int) -> None:
    """Resume range instances."""
    raise NotImplementedError


def connect_terminal(user: User, range_id: int, instance_type: str) -> Any:
    """Get SSH connection to instance."""
    raise NotImplementedError
