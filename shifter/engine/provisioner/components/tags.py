"""Shared AWS resource tagging utilities for Shifter provisioner components.

This module provides a consistent tagging standard for all AWS resources created
by Shifter. Every resource that accepts tags should use build_common_tags() to
ensure proper correlation with database records for:
- Cost tracking and allocation
- Resource cleanup and sweeping
- Orphan detection
- AWS console → DB record lookup

Tagging Standard:
    Every resource gets:
    - shifter:request_uuid - always (correlates to Request record)
    - shifter:user_id - always
    - shifter:environment - always
    - shifter:system - always ("shifter")
    - ManagedBy - always ("terraform")

    Plus component-specific tags:
    - NetworkComponent: shifter:subnet_uuid, shifter:subnet_name
    - InstanceComponent: shifter:instance_uuid
    - NGFWComponent: shifter:instance_uuid
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

# Valid unit types for component-specific UUID tags
UnitType = Literal["subnet", "instance"]


def build_common_tags(
    user_id: int,
    environment: str,
    request_uuid: str,
    *,
    range_id: int | None = None,
    unit_type: UnitType | None = None,
    unit_uuid: str | None = None,
    unit_name: str | None = None,
    component: str | None = None,
) -> dict[str, str]:
    """Build standard tags for AWS resources.

    All Shifter-managed AWS resources should use this function to ensure
    consistent tagging for cost tracking, cleanup, and traceability.

    Args:
        user_id: Owner's Django user ID. Required.
        environment: Deployment environment (dev, staging, prod). Required.
        request_uuid: UUID of the Request record (primary correlation key). Required.
        range_id: Optional range ID (for range resources, not NGFW-only resources).
        unit_type: Type of unit this resource belongs to ("subnet" or "instance").
        unit_uuid: UUID of the unit (subnet or instance). Required if unit_type is set.
        unit_name: Optional human-readable name for the unit (e.g., subnet name).
        component: Optional component identifier (e.g., "ngfw", "range").

    Returns:
        Dictionary of tag key-value pairs ready for AWS resource creation.

    Raises:
        ValueError: If required parameters are missing or invalid.

    Example:
        # For a subnet resource:
        tags = build_common_tags(
            user_id=42,
            environment="prod",
            request_uuid="abc-123",
            range_id=1,
            unit_type="subnet",
            unit_uuid="subnet-uuid-456",
            unit_name="attack_network",
        )

        # For an NGFW instance resource:
        tags = build_common_tags(
            user_id=42,
            environment="prod",
            request_uuid="abc-123",
            unit_type="instance",
            unit_uuid="ngfw-instance-uuid",
            component="ngfw",
        )
    """
    # Input validation
    if user_id is None:
        raise ValueError("user_id is required")
    if not isinstance(user_id, int) or user_id < 0:
        raise ValueError(f"user_id must be a non-negative integer, got {user_id!r}")

    if not environment:
        raise ValueError("environment is required")
    if not isinstance(environment, str):
        raise ValueError(f"environment must be a string, got {type(environment).__name__}")

    if not request_uuid:
        raise ValueError("request_uuid is required")
    if not isinstance(request_uuid, str):
        raise ValueError(f"request_uuid must be a string, got {type(request_uuid).__name__}")

    # Validate unit_type and unit_uuid together
    if unit_type is not None and not unit_uuid:
        raise ValueError(f"unit_uuid is required when unit_type is set (unit_type={unit_type!r})")
    if unit_uuid is not None and not unit_type:
        raise ValueError(f"unit_type is required when unit_uuid is set (unit_uuid={unit_uuid!r})")
    if unit_type is not None and unit_type not in ("subnet", "instance"):
        raise ValueError(f"unit_type must be 'subnet' or 'instance', got {unit_type!r}")

    # Build base tags (always present)
    tags: dict[str, str] = {
        "shifter:user_id": str(user_id),
        "shifter:environment": environment,
        "shifter:request_uuid": request_uuid,
        "shifter:system": "shifter",
        "ManagedBy": "terraform",
    }

    # Add optional range_id
    if range_id is not None:
        if not isinstance(range_id, int) or range_id < 0:
            raise ValueError(f"range_id must be a non-negative integer, got {range_id!r}")
        tags["shifter:range_id"] = str(range_id)

    # Add unit-specific tags
    if unit_type and unit_uuid:
        tags[f"shifter:{unit_type}_uuid"] = unit_uuid
        if unit_name:
            tags[f"shifter:{unit_type}_name"] = unit_name

    # Add component identifier
    if component:
        tags["shifter:component"] = component

    logger.debug(
        "Built common tags: user_id=%s request_uuid=%s unit_type=%s unit_uuid=%s",
        user_id,
        request_uuid,
        unit_type,
        unit_uuid,
    )

    return tags
