"""CTF signal receivers for CMS events.

Connects to CMS signals to keep CTF data in sync with range status changes.
"""

from __future__ import annotations

import logging

from django.dispatch import receiver

from cms.services import range_status_changed

logger = logging.getLogger(__name__)


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
