"""Engine services package.

Exposes the engine service interface for infrastructure lifecycle.
"""

from __future__ import annotations

from typing import Any


def create_range(range_config: dict[str, Any]) -> int:
    """Provision infrastructure for range.

    Args:
        range_config: Fully resolved configuration dict containing
            scenario_id, instances, and agent details from CMS hydrator.

    Returns:
        range_id: The ID of the created range.

    Raises:
        NotImplementedError: This is a stub - implementation pending.
    """
    raise NotImplementedError("create_range not yet implemented")
