"""Lifecycle transitions for scoped communications (ADR-051, #2048).

Cancellation, participant removal, event cancellation, and range replacement have
explicit, bounded delivery and retention behavior (AC3). Cancellation stops only
not-yet-claimed work; it can never recall a provider-accepted send. The immutable,
event-qualified snapshot identity always survives as bounded historical evidence
and is never retargeted; only its encrypted delivery coordinate is erased.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ctf.enums_communication import CampaignStatus, DeliveryStatus, IntentStatus
from ctf.models import (
    CommunicationCampaign,
    CommunicationIntent,
    CTFEvent,
    CTFParticipant,
    DeliveryAttempt,
    RecipientSnapshot,
)

logger = logging.getLogger(__name__)

# Delivery commands that have not yet been claimed by a transport worker; only
# these can be cancelled. Claimed/accepted/permanently-failed attempts keep their
# truthful terminal state.
_UNCLAIMED = (DeliveryStatus.QUEUED.value, DeliveryStatus.RETRY_DUE.value)


def _cancel_unclaimed(attempts_q: Q, now: datetime) -> int:
    """Cancel the not-yet-claimed delivery commands matching ``attempts_q``."""
    return DeliveryAttempt.objects.filter(attempts_q, status__in=_UNCLAIMED).update(
        status=DeliveryStatus.CANCELLED.value, updated_at=now
    )


def cancel_campaign(campaign: CommunicationCampaign) -> int:
    """Cancel a campaign: stop unclaimed work, leave accepted history truthful.

    Returns the number of delivery commands cancelled.
    """
    now = timezone.now()
    with transaction.atomic():
        # Lock the campaign so a concurrent release (which also locks it) cannot
        # materialize new work between this cancellation and its commit.
        CommunicationCampaign.objects.select_for_update().get(pk=campaign.pk)
        cancelled = _cancel_unclaimed(Q(intent__campaign=campaign), now)
        CommunicationIntent.objects.filter(campaign=campaign).exclude(
            status__in=(IntentStatus.CANCELLED.value, IntentStatus.FENCED.value)
        ).update(status=IntentStatus.CANCELLED.value, updated_at=now)
        CommunicationCampaign.objects.filter(pk=campaign.pk).update(
            status=CampaignStatus.CANCELLED.value, updated_at=now
        )
    logger.info("Cancelled communication campaign %s (%d unclaimed deliveries stopped)", campaign.id, cancelled)
    return cancelled


def on_participant_removed(participant: CTFParticipant) -> int:
    """React to a participant removal/deletion (AC3).

    Cancels that participation's unclaimed delivery commands and erases its
    encrypted delivery coordinate from every snapshot, while the immutable
    event-qualified snapshot identity remains as bounded evidence (never
    retargeted). Read/acknowledgement authority is revoked live at the inbox
    boundary through the parent-scoped participant predicate. Returns the number
    of delivery commands cancelled.
    """
    now = timezone.now()
    with transaction.atomic():
        # Take the participant's event lock first (the canonical event-first order
        # shared with release), so a concurrent release that also locks that event
        # cannot resolve and materialize this participant into new snapshots after
        # this fence runs. The caller commits the removal and this fence together.
        CTFEvent.objects.select_for_update().filter(pk=participant.event_id).first()
        snapshots = RecipientSnapshot.objects.filter(participant_public_id=participant.id)
        cancelled = _cancel_unclaimed(Q(snapshot__in=snapshots), now)
        snapshots.update(delivery_coordinate="", updated_at=now)
    logger.info("Handled participant %s removal for communications (%d deliveries stopped)", participant.id, cancelled)
    return cancelled


def on_event_cancelled(event: CTFEvent) -> int:
    """React to an event cancellation (AC3).

    Fences scheduled intents targeting the event so they can never materialize new
    work, and cancels the event-qualified unclaimed delivery commands. An already
    released multi-event intent keeps its work for other events; only work
    qualified to the cancelled event is stopped. Returns commands cancelled.
    """
    now = timezone.now()
    with transaction.atomic():
        # Lock the event row so a concurrent release (which locks its target
        # events) cannot materialize event-qualified work past this fence.
        CTFEvent.objects.select_for_update().get(pk=event.pk)
        CommunicationIntent.objects.filter(campaign__target_events=event, status=IntentStatus.SCHEDULED.value).update(
            status=IntentStatus.FENCED.value, updated_at=now
        )
        cancelled = _cancel_unclaimed(Q(snapshot__event=event), now)
    logger.info("Handled event %s cancellation for communications (%d deliveries stopped)", event.pk, cancelled)
    return cancelled


def on_range_replaced(range_generation_ref: str) -> int:
    """React to a range replacement (AC3).

    Fences all unclaimed generation-bound work for the old generation: scheduled
    intents bound to it become fenced and their unclaimed delivery commands are
    cancelled. A replacement range requires a new generation-qualified occurrence
    and idempotency identity; the old records remain historical evidence. Returns
    commands cancelled.
    """
    if not range_generation_ref:
        return 0
    now = timezone.now()
    with transaction.atomic():
        CommunicationIntent.objects.filter(
            range_generation_ref=range_generation_ref, status=IntentStatus.SCHEDULED.value
        ).update(status=IntentStatus.FENCED.value, updated_at=now)
        cancelled = _cancel_unclaimed(Q(intent__range_generation_ref=range_generation_ref), now)
    logger.info("Fenced communications for replaced range generation (%d deliveries stopped)", cancelled)
    return cancelled
