"""Lifecycle + retention behavior for scoped communications (ADR-051, #2048).

Covers AC3: cancellation stops only not-yet-claimed work and never recalls an
accepted send; participant removal, event cancellation, and range replacement
have explicit delivery behavior; and content/coordinates are physically purged
after the retention window. Each test drives the real services and asserts the
effect.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.enums_communication import DeliveryStatus, IntentStatus
from ctf.models import (
    CommunicationCampaign,
    CommunicationIntent,
    CTFEvent,
    CTFParticipant,
    DeliveryAttempt,
    MessageRevision,
    RecipientSnapshot,
)
from ctf.services.communication import (
    CampaignDraft,
    cancel_campaign,
    create_campaign,
    on_event_cancelled,
    on_participant_removed,
    on_range_replaced,
    purge_expired_communications,
    release_campaign,
)

pytestmark = pytest.mark.django_db


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participant(event, email):
    return CTFParticipant.objects.create(
        event=event,
        email=email,
        name=email.split("@")[0],
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


def _released_campaign(organizer_user, ctf_event, *, occurrence="occ", range_generation_ref=""):
    _participant(ctf_event, "a@test.com")
    campaign = create_campaign(
        organizer_user,
        _workspace_uuid(organizer_user),
        CampaignDraft(
            title="Kickoff",
            origin="organizer_staff",
            target_event_ids=[ctf_event.id],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
            trigger_spec={"kind": "manual"},
            channels=["in_app", "email"],
            subject="Welcome",
            body="Hello",
        ),
    )
    intent = release_campaign(
        campaign, occurrence_key=occurrence, actor_user_id=organizer_user.id, range_generation_ref=range_generation_ref
    )
    return campaign, intent


def test_cancel_campaign_stops_unclaimed_work_but_keeps_accepted_history(organizer_user, ctf_event):
    campaign, intent = _released_campaign(organizer_user, ctf_event)
    # Simulate one command already accepted by a transport backend.
    accepted = DeliveryAttempt.objects.filter(intent=intent, channel="email").first()
    DeliveryAttempt.objects.filter(pk=accepted.pk).update(status=DeliveryStatus.ACCEPTED.value)

    cancel_campaign(campaign)

    campaign.refresh_from_db()
    assert campaign.status == "cancelled"
    accepted.refresh_from_db()
    assert accepted.status == DeliveryStatus.ACCEPTED.value  # accepted send is not recalled
    assert not DeliveryAttempt.objects.filter(intent=intent, status=DeliveryStatus.QUEUED.value).exists()
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.CANCELLED.value


def test_participant_removal_erases_the_coordinate_and_stops_unclaimed_work(organizer_user, ctf_event):
    _campaign, intent = _released_campaign(organizer_user, ctf_event)
    snapshot = RecipientSnapshot.objects.get(intent=intent)
    participant = CTFParticipant.objects.get(pk=snapshot.participant_public_id)

    on_participant_removed(participant)

    snapshot.refresh_from_db()
    # Snapshot identity survives as evidence; its coordinate is erased.
    assert snapshot.participant_public_id == participant.id
    assert snapshot.delivery_coordinate == ""
    assert not DeliveryAttempt.objects.filter(snapshot=snapshot, status=DeliveryStatus.QUEUED.value).exists()


def test_event_cancellation_stops_event_qualified_unclaimed_work(organizer_user, ctf_event):
    _released_campaign(organizer_user, ctf_event)

    on_event_cancelled(ctf_event)

    assert not DeliveryAttempt.objects.filter(snapshot__event=ctf_event, status=DeliveryStatus.QUEUED.value).exists()


def test_range_replacement_fences_scheduled_intents_and_stops_unclaimed_work(organizer_user, ctf_event):
    campaign, _released = _released_campaign(
        organizer_user, ctf_event, occurrence="occ-rng", range_generation_ref="gen-1"
    )
    revision = MessageRevision.objects.filter(campaign=campaign).first()
    scheduled = CommunicationIntent.objects.create(
        campaign=campaign,
        revision=revision,
        status=IntentStatus.SCHEDULED.value,
        trigger_kind="range_signal",
        origin="dynamic_raes",
        channels=["in_app"],
        acknowledgement_policy="none",
        occurrence_key="sched-1",
        idempotency_key="sched-1|gen-1",
        range_generation_ref="gen-1",
    )

    on_range_replaced("gen-1")

    scheduled.refresh_from_db()
    assert scheduled.status == IntentStatus.FENCED.value
    assert not DeliveryAttempt.objects.filter(
        intent__range_generation_ref="gen-1", status=DeliveryStatus.QUEUED.value
    ).exists()


def test_retention_purges_communications_past_the_window(organizer_user):
    past_event = CTFEvent.objects.create(
        name="Long over",
        created_by=organizer_user,
        workspace_id=workspace_services.resolve_personal_workspace(organizer_user).workspace_id,
        event_start=timezone.now() - timedelta(days=200),
        event_end=timezone.now() - timedelta(days=199),
    )
    campaign, intent = _released_campaign(organizer_user, past_event, occurrence="occ-old")

    result = purge_expired_communications(retention_days=90)

    assert result["campaigns_purged"] == 1
    assert not CommunicationCampaign.objects.filter(pk=campaign.pk).exists()
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()
    assert not MessageRevision.objects.filter(campaign=campaign).exists()


def test_retention_keeps_communications_within_the_window(organizer_user, ctf_event):
    campaign, _intent = _released_campaign(organizer_user, ctf_event, occurrence="occ-recent")

    result = purge_expired_communications(retention_days=90)

    assert result["campaigns_purged"] == 0
    assert CommunicationCampaign.objects.filter(pk=campaign.pk).exists()
