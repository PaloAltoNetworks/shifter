"""CTF event-to-CMS range lease reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctf.models import CTFEvent


def reconcile_event_range_leases(event: CTFEvent) -> int:
    """Apply the event's cleanup time to participant and spare ranges."""
    from ctf import bridges

    participant_ids = event.participants.filter(range_instance_id__isnull=False).values_list(
        "range_instance_id", flat=True
    )
    spare_ids = event.spare_ranges.filter(range_instance_id__isnull=False).values_list("range_instance_id", flat=True)
    range_instance_ids = sorted(
        {instance_id for instance_id in (*participant_ids, *spare_ids) if instance_id is not None}
    )
    return bridges.cms_reconcile_ctf_range_leases(range_instance_ids, event.get_cleanup_time())
