"""Range rows that remain eligible for user-requested resource cleanup."""

from django.db.models import Q, QuerySet

from cms.models import RangeInstance
from shared.enums import ResourceStatus


def destroyable_instances() -> QuerySet[RangeInstance]:
    """Include failed rows because failure does not prove resource cleanup."""
    return RangeInstance.all_objects.filter(Q(deleted_at__isnull=True) | Q(status=ResourceStatus.FAILED.value))
