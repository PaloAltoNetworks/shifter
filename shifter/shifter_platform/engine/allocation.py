"""Subnet index allocation service.

This module handles allocation of subnet indices for new ranges,
ensuring no conflicts between active ranges.
"""

from django.db import transaction

from engine.models import Range


class AllocationError(Exception):
    """Error raised when subnet allocation fails.

    Typically occurs when all 254 subnet indices are in use.
    """


def allocate_subnet_index() -> int:
    """Allocate the next available subnet index for a new range.

    Uses SELECT FOR UPDATE to prevent race conditions when multiple
    ranges are being created concurrently.

    Returns:
        int: The allocated subnet index (1-254)

    Raises:
        AllocationError: If no subnet indices are available (254 active ranges)
    """
    with transaction.atomic():
        # Lock rows to prevent race conditions
        # Get all subnet_index values currently in use by active ranges
        # Exclude terminal states - those ranges don't have AWS resources
        used_indices = set(
            Range.objects.select_for_update()
            .exclude(status__in=Range.TERMINAL_STATUSES)
            .exclude(subnet_index__isnull=True)
            .values_list("subnet_index", flat=True)
        )

        # Find the first available index
        for index in range(Range.SUBNET_INDEX_MIN, Range.SUBNET_INDEX_MAX + 1):
            if index not in used_indices:
                return index

        raise AllocationError(
            f"No subnet indices available. Maximum {Range.SUBNET_INDEX_MAX} "
            "concurrent ranges supported. Destroy some ranges first."
        )
