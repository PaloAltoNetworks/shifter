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


@receiver(range_status_changed)
def sync_ctf_spare_range_status(
    sender: None,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs,
) -> None:
    """Update CTFSpareRange.status when CMS reports a status change (#1018).

    This is the "existing event projection" that a spare's status uses to
    reach ``ready``/``failed`` -- no separate polling loop is introduced for
    the spare pool. Only unconsumed spares are touched: once a spare is
    consumed, its range belongs to the participant and further status
    changes are the participant-range projection's concern
    (:func:`sync_ctf_participant_range_status`), not the pool's.
    """
    from ctf.enums import SpareRangeStatus
    from ctf.models import CTFSpareRange
    from shared.enums import ResourceStatus

    status_map = {
        ResourceStatus.READY.value: SpareRangeStatus.READY.value,
        ResourceStatus.FAILED.value: SpareRangeStatus.FAILED.value,
    }
    mapped_status = status_map.get(new_status)
    if mapped_status is None:
        return

    spares = CTFSpareRange.objects.filter(
        range_instance_id=range_instance_id,
        consumed_by__isnull=True,
    )

    updated = 0
    for spare in spares:
        if spare.status != mapped_status:
            spare.status = mapped_status
            spare.save(update_fields=["status", "updated_at"])
            updated += 1

    if updated:
        logger.info(
            "Synced spare status=%s for %d CTF spare range(s) (range_instance_id=%s, was=%s)",
            mapped_status,
            updated,
            range_instance_id,
            previous_status,
        )
