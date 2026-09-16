"""Scoped-communication domain model constraints and immutability (ADR-051, #2048).

Drives the real models against real rows. Covers the issue's DB-constraint and
immutability acceptance criteria: idempotency uniqueness, per-recipient
uniqueness (deduplication), immutable revisions, and closed-shape validation. The
security-critical uniqueness rules are also asserted at the DATABASE level via
``bulk_create`` (which bypasses ``full_clean``), because migrations, bulk
operations, and ``QuerySet.update()`` bypass model validation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ctf.models import (
    CommunicationCampaign,
    CommunicationIntent,
    DeliveryAttempt,
    MessageRevision,
    ParticipantReceipt,
    RecipientSnapshot,
)

pytestmark = pytest.mark.django_db


def _campaign(ctf_event, organizer_user, **overrides):
    data = {
        "workspace_id": ctf_event.workspace_id,
        "title": "Kickoff",
        "origin": "organizer_staff",
        "created_by": organizer_user,
        "audience_spec": {"kind": "event", "event_ids": [str(ctf_event.id)]},
        "trigger_spec": {"kind": "manual"},
        "channels": ["in_app"],
        "acknowledgement_policy": "none",
    }
    data.update(overrides)
    return CommunicationCampaign.objects.create(**data)


def _revision(campaign, number=1):
    return MessageRevision.objects.create(
        campaign=campaign,
        revision_number=number,
        subject="Hello",
        body="Welcome",
        content_digest=f"sha256:{'0' * 64}",
    )


def _intent(campaign, revision, key):
    return CommunicationIntent.objects.create(
        campaign=campaign,
        revision=revision,
        status="released",
        trigger_kind="manual",
        origin="organizer_staff",
        channels=["in_app"],
        acknowledgement_policy="none",
        occurrence_key=key,
        idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# Campaign closed-shape validation
# ---------------------------------------------------------------------------


def test_campaign_with_valid_shapes_is_created(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    assert campaign.pk is not None
    assert campaign.status == "draft"


def test_campaign_rejects_an_audience_with_email_addresses(ctf_event, organizer_user):
    with pytest.raises(ValidationError):
        _campaign(ctf_event, organizer_user, audience_spec={"kind": "participant", "emails": ["a@b.com"]})


def test_campaign_rejects_an_unknown_trigger_kind(ctf_event, organizer_user):
    with pytest.raises(ValidationError):
        _campaign(ctf_event, organizer_user, trigger_spec={"kind": "webhook"})


def test_campaign_rejects_empty_channels(ctf_event, organizer_user):
    with pytest.raises(ValidationError):
        _campaign(ctf_event, organizer_user, channels=[])


# ---------------------------------------------------------------------------
# Message revision immutability + uniqueness
# ---------------------------------------------------------------------------


def test_message_revision_content_is_immutable(ctf_event, organizer_user):
    revision = _revision(_campaign(ctf_event, organizer_user))
    reloaded = MessageRevision.objects.get(pk=revision.pk)
    reloaded.body = "Rewritten"

    with pytest.raises(ValidationError):
        reloaded.save()


def test_message_revision_created_instance_is_immutable_without_reload(ctf_event, organizer_user):
    # The instance returned by objects.create() (never reloaded) must still be
    # immutable when modified and saved (codex finding: from_db baseline gap).
    revision = _revision(_campaign(ctf_event, organizer_user))
    revision.body = "Rewritten in place"

    with pytest.raises(ValidationError):
        revision.save()


def test_message_revision_deferred_load_is_immutable(ctf_event, organizer_user):
    revision = _revision(_campaign(ctf_event, organizer_user))
    deferred = MessageRevision.objects.only("id", "campaign").get(pk=revision.pk)
    deferred.subject = "Changed via deferred load"

    with pytest.raises(ValidationError):
        deferred.save()


def test_message_revision_number_is_unique_per_campaign(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    _revision(campaign, number=1)

    with pytest.raises(ValidationError):
        _revision(campaign, number=1)


# ---------------------------------------------------------------------------
# Intent idempotency uniqueness (app boundary AND database)
# ---------------------------------------------------------------------------


def test_intent_idempotency_key_is_unique_at_the_app_boundary(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    revision = _revision(campaign)
    _intent(campaign, revision, key="occ-1")

    with pytest.raises(ValidationError):
        _intent(campaign, revision, key="occ-1")


def test_intent_idempotency_key_is_unique_in_the_database(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    revision = _revision(campaign)
    _intent(campaign, revision, key="occ-db")

    # bulk_create bypasses full_clean, so only the DB constraint stands between a
    # replayed occurrence and a duplicate intent.
    duplicate = CommunicationIntent(
        campaign=campaign,
        revision=revision,
        status="released",
        trigger_kind="manual",
        origin="organizer_staff",
        channels=["in_app"],
        acknowledgement_policy="none",
        occurrence_key="occ-db",
        idempotency_key="occ-db",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        CommunicationIntent.objects.bulk_create([duplicate])


# ---------------------------------------------------------------------------
# Recipient snapshot deduplication (app boundary AND database)
# ---------------------------------------------------------------------------


def test_recipient_snapshot_is_deduplicated_per_intent(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    intent = _intent(campaign, _revision(campaign), key="occ-dedup")
    participant_id = uuid4()
    RecipientSnapshot.objects.create(intent=intent, event=ctf_event, participant_public_id=participant_id)

    with pytest.raises(ValidationError):
        RecipientSnapshot.objects.create(intent=intent, event=ctf_event, participant_public_id=participant_id)


def test_recipient_snapshot_dedup_is_enforced_in_the_database(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    intent = _intent(campaign, _revision(campaign), key="occ-dedup-db")
    participant_id = uuid4()
    RecipientSnapshot.objects.create(intent=intent, event=ctf_event, participant_public_id=participant_id)
    duplicate = RecipientSnapshot(intent=intent, event=ctf_event, participant_public_id=participant_id)

    with pytest.raises(IntegrityError), transaction.atomic():
        RecipientSnapshot.objects.bulk_create([duplicate])


# ---------------------------------------------------------------------------
# Delivery + receipt
# ---------------------------------------------------------------------------


def test_delivery_attempt_is_unique_per_snapshot_and_channel(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    intent = _intent(campaign, _revision(campaign), key="occ-deliver")
    snapshot = RecipientSnapshot.objects.create(intent=intent, event=ctf_event, participant_public_id=uuid4())
    DeliveryAttempt.objects.create(intent=intent, snapshot=snapshot, channel="email", idempotency_key="d1")

    with pytest.raises(ValidationError):
        DeliveryAttempt.objects.create(intent=intent, snapshot=snapshot, channel="email", idempotency_key="d2")


def test_participant_receipt_is_one_per_snapshot(ctf_event, organizer_user):
    campaign = _campaign(ctf_event, organizer_user)
    intent = _intent(campaign, _revision(campaign), key="occ-receipt")
    snapshot = RecipientSnapshot.objects.create(intent=intent, event=ctf_event, participant_public_id=uuid4())
    ParticipantReceipt.objects.create(snapshot=snapshot)

    with pytest.raises(ValidationError):
        ParticipantReceipt.objects.create(snapshot=snapshot)
