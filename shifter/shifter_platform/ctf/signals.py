"""CTF signals for cross-domain event propagation.

Provides a Django signal that CMS fires when a RangeInstance status changes,
allowing CTF to update its cached CTFParticipant.range_status without
direct coupling from CMS → CTF models.
"""

from __future__ import annotations

import logging

from django.dispatch import Signal, receiver

logger = logging.getLogger(__name__)

# Fired by CMS handlers.py after updating RangeInstance.status.
# Kwargs: range_instance_id (int), new_status (str), previous_status (str)
range_status_changed = Signal()


@receiver(range_status_changed)
def sync_ctf_participant_range_status(
    sender,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs,
) -> None:
    """Update CTFParticipant.range_status when CMS reports a status change."""
    from ctf.models import CTFParticipant

    participants = CTFParticipant.objects.filter(
        range_instance_id=range_instance_id,
    )

    updated = 0
    for participant in participants:
        if participant.range_status != new_status:
            participant.range_status = new_status
            participant.save(update_fields=["range_status", "updated_at"])
            updated += 1

    if updated:
        logger.info(
            "Synced range_status=%s for %d CTF participant(s) (range_instance_id=%s, was=%s)",
            new_status,
            updated,
            range_instance_id,
            previous_status,
        )
