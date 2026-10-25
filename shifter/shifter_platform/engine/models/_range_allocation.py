"""Range allocation methods kept separate from the persistent range schema."""

from __future__ import annotations

from typing import Any

from django.db import transaction


class RangeAllocationMixin:
    """Provide serialized subnet and VPN-pool allocation to the Range model."""

    SUBNET_INDEX_MIN = 1
    SUBNET_INDEX_MAX = 4048

    @classmethod
    def allocate_subnet_index(cls: type[Any]) -> int:
        """Allocate the first free subnet index while holding the range-table lock."""
        from django.db import connection

        with transaction.atomic():
            if connection.vendor != "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("LOCK TABLE mission_control_range IN EXCLUSIVE MODE")
            used_indices = set(
                cls.objects.exclude(status__in=[cls.Status.DESTROYED, cls.Status.FAILED])
                .exclude(subnet_index__isnull=True)
                .values_list("subnet_index", flat=True)
            )
            for index in range(cls.SUBNET_INDEX_MIN, cls.SUBNET_INDEX_MAX + 1):
                if index not in used_indices:
                    return index
            raise ValueError(
                f"No subnet indices available. Maximum {cls.SUBNET_INDEX_MAX} "
                "concurrent ranges supported. Destroy some ranges first."
            )
