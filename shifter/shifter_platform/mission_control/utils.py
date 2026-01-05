"""Utility functions for Mission Control."""

from collections.abc import Iterable

from shared.schemas import InstanceContext


def build_connection_urls(instances: Iterable[InstanceContext]) -> list[dict]:
    """Build terminal WebSocket connection URLs from instances.

    Args:
        instances: Iterable of InstanceContext objects with uuid

    Returns:
        List of dicts with uuid and terminal_url for each instance
    """
    return [{"uuid": inst.uuid, "terminal_url": f"/ws/terminal/{inst.uuid}/"} for inst in instances]
