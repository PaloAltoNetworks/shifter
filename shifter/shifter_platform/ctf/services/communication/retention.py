"""Retention purge for scoped communications (ADR-051, #2048).

Communication content, recipient snapshots, encrypted delivery coordinates,
attempts, and receipts are retained until the configured window after the latest
target event ends, then physically purged -- never left as a restorable
soft-deleted row that still holds a body or a coordinate. Body-free ``shared.audit``
evidence is untouched and follows the audit system's own archive policy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ctf.models import CommunicationCampaign, CommunicationIntent, MessageRevision, RecipientSnapshot

logger = logging.getLogger(__name__)


def purge_expired_communications(*, now: datetime | None = None, retention_days: int | None = None) -> dict[str, int]:
    """Hard-purge communications whose retention window has elapsed.

    A campaign is expired when the latest of its target events ended more than
    ``retention_days`` ago. Deleting the campaign cascades its intents, message
    revisions, recipient snapshots, delivery attempts, and receipts with a bulk
    ``QuerySet.delete`` (a real delete, not the soft-delete escape hatch), so the
    bodies and encrypted coordinates are erased. Returns bounded counts.
    """
    now = now or timezone.now()
    if retention_days is None:
        retention_days = settings.CTF_COMMUNICATION_RETENTION_DAYS
    cutoff = now - timedelta(days=retention_days)

    expired = (
        CommunicationCampaign.objects.annotate(latest_event_end=Max("target_events__event_end"))
        .filter(latest_event_end__isnull=False, latest_event_end__lt=cutoff)
        .values_list("id", flat=True)
    )
    campaign_ids = list(expired)
    if not campaign_ids:
        return {"campaigns_purged": 0, "revisions_purged": 0, "snapshots_purged": 0}

    revisions = MessageRevision.objects.filter(campaign_id__in=campaign_ids).count()
    snapshots = RecipientSnapshot.objects.filter(intent__campaign_id__in=campaign_ids).count()
    # Delete in dependency order: an intent PROTECT-references its pinned revision,
    # so intents (and their cascaded snapshots/attempts/receipts) must go before
    # the revisions, then the campaigns (which cascade the target-event links). All
    # of these are real bulk deletes, not the soft-delete escape hatch.
    with transaction.atomic():
        CommunicationIntent.objects.filter(campaign_id__in=campaign_ids).delete()
        MessageRevision.objects.filter(campaign_id__in=campaign_ids).delete()
        CommunicationCampaign.objects.filter(id__in=campaign_ids).delete()

    result = {
        "campaigns_purged": len(campaign_ids),
        "revisions_purged": revisions,
        "snapshots_purged": snapshots,
    }
    logger.info(
        "Purged expired communications: %d campaigns, %d revisions, %d snapshots",
        result["campaigns_purged"],
        result["revisions_purged"],
        result["snapshots_purged"],
    )
    return result
