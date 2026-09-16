"""Confinement, audience resolution, and release for scoped communications.

Covers ADR-051 / #2048 acceptance criteria AC1 (cross-event workspace
confinement + per-event authorization), the single audience resolver, and AC2
(deterministic, deduplicated, event-qualified recipient snapshots that a retry
cannot grow). Every test drives the real services and asserts the effect.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import (
    CommunicationIntent,
    CTFEvent,
    CTFParticipant,
    DeliveryAttempt,
    ParticipantReceipt,
    RecipientSnapshot,
)
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign, resolve_recipients

pytestmark = pytest.mark.django_db

User = get_user_model()


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participant(event, email, *, status=ParticipantStatus.ACTIVE.value, team=None):
    return CTFParticipant.objects.create(
        event=event,
        email=email,
        name=email.split("@")[0],
        status=status,
        team=team,
        registered_at=timezone.now(),
    )


def _draft(ctf_event, **overrides) -> CampaignDraft:
    data = {
        "title": "Kickoff",
        "origin": "organizer_staff",
        "target_event_ids": [ctf_event.id],
        "audience_spec": {"kind": "event", "event_ids": [str(ctf_event.id)]},
        "trigger_spec": {"kind": "manual"},
        "channels": ["in_app", "email"],
        "subject": "Welcome",
        "body": "Read the rules at [rules](/events/rules).",
    }
    data.update(overrides)
    return CampaignDraft(**data)


# ---------------------------------------------------------------------------
# AC1: confinement + per-event authorization
# ---------------------------------------------------------------------------


def test_owner_can_create_a_campaign_for_their_event(organizer_user, ctf_event):
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event))

    assert campaign.status == "draft"
    assert campaign.workspace_id == ctf_event.workspace_id
    assert list(campaign.target_events.values_list("id", flat=True)) == [ctf_event.id]
    assert campaign.message_revisions.count() == 1


def test_campaign_cannot_target_an_event_in_a_different_workspace(organizer_user, ctf_event):
    foreign_event = CTFEvent.objects.create(
        name="Foreign",
        created_by=organizer_user,
        workspace_id=ctf_event.workspace_id + 99999,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=2),
    )
    ws = _workspace_uuid(organizer_user)
    draft = _draft(
        ctf_event,
        target_event_ids=[foreign_event.id],
        audience_spec={"kind": "event", "event_ids": [str(foreign_event.id)]},
    )

    with pytest.raises(CTFCommunicationError):
        create_campaign(organizer_user, ws, draft)


def test_campaign_cannot_target_an_event_without_notification_capability(
    organizer_user, second_organizer_user, ctf_event
):
    # Same workspace scope, but owned by another organizer: the author holds no
    # notification capability on it, so it must be denied (opaque).
    others_event = CTFEvent.objects.create(
        name="Someone else's",
        created_by=second_organizer_user,
        workspace_id=ctf_event.workspace_id,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=2),
    )
    ws = _workspace_uuid(organizer_user)
    draft = _draft(
        ctf_event,
        target_event_ids=[others_event.id],
        audience_spec={"kind": "event", "event_ids": [str(others_event.id)]},
    )

    with pytest.raises(CTFCommunicationError):
        create_campaign(organizer_user, ws, draft)


def test_campaign_creation_denies_a_workspace_the_author_does_not_belong_to(organizer_user, ctf_event):
    outsider = User.objects.create_user(username="outsider@e.com", email="outsider@e.com")
    outsider_workspace = _workspace_uuid(outsider)
    draft = _draft(ctf_event)

    with pytest.raises(CTFCommunicationError):
        create_campaign(organizer_user, outsider_workspace, draft)


# ---------------------------------------------------------------------------
# Audience resolution
# ---------------------------------------------------------------------------


def test_event_audience_resolves_viewing_participants_deterministically(ctf_event):
    p2 = _participant(ctf_event, "b@test.com")
    p1 = _participant(ctf_event, "a@test.com")
    _participant(ctf_event, "banned@test.com", status=ParticipantStatus.BANNED.value)

    resolved = resolve_recipients({ctf_event.id}, {"kind": "event", "event_ids": [str(ctf_event.id)]})

    ids = [p.id for p in resolved]
    assert set(ids) == {p1.id, p2.id}  # banned participant excluded
    assert ids == sorted(ids)  # deterministic ordering


def test_audience_referencing_a_non_target_event_is_rejected(ctf_event):
    other = CTFEvent.objects.create(
        name="Other",
        created_by=ctf_event.created_by,
        workspace_id=ctf_event.workspace_id,
        event_start=timezone.now() + timedelta(days=1),
        event_end=timezone.now() + timedelta(days=1, hours=2),
    )
    with pytest.raises(CTFCommunicationError):
        resolve_recipients({ctf_event.id}, {"kind": "event", "event_ids": [str(other.id)]})


# ---------------------------------------------------------------------------
# AC2: release materializes deterministic, deduplicated recipients
# ---------------------------------------------------------------------------


def test_release_materializes_snapshots_receipts_and_delivery_commands(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    _participant(ctf_event, "b@test.com")
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event))

    intent = release_campaign(campaign, occurrence_key="occ-1", actor_user_id=organizer_user.id)

    assert intent.status == "released"
    snapshots = RecipientSnapshot.objects.filter(intent=intent)
    assert snapshots.count() == 2
    assert all(s.event_id == ctf_event.id for s in snapshots)  # event-qualified
    assert ParticipantReceipt.objects.filter(snapshot__intent=intent).count() == 2
    # Two channels -> two delivery commands per recipient.
    assert DeliveryAttempt.objects.filter(intent=intent).count() == 4
    assert set(DeliveryAttempt.objects.filter(intent=intent).values_list("status", flat=True)) == {"queued"}


def test_release_is_idempotent_and_never_grows_the_audience(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event))

    first = release_campaign(campaign, occurrence_key="occ-dup", actor_user_id=organizer_user.id)
    second = release_campaign(campaign, occurrence_key="occ-dup", actor_user_id=organizer_user.id)

    assert first.id == second.id
    assert CommunicationIntent.objects.filter(campaign=campaign).count() == 1
    assert RecipientSnapshot.objects.filter(intent=first).count() == 1


def test_release_encrypts_the_delivery_coordinate_at_rest(organizer_user, ctf_event):
    _participant(ctf_event, "secret@test.com")
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event))

    intent = release_campaign(campaign, occurrence_key="occ-enc", actor_user_id=organizer_user.id)
    snapshot = RecipientSnapshot.objects.get(intent=intent)

    # The decrypted coordinate round-trips through the model...
    assert snapshot.delivery_coordinate == "secret@test.com"
    # ...but the stored column is ciphertext, never the plain address. Read the raw
    # column directly because the field transparently decrypts on every ORM read.
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT delivery_coordinate FROM ctf_communication_recipient_snapshot")
        raw = cursor.fetchone()[0]
    assert raw.startswith("enc:v1:")
    assert "secret@test.com" not in raw


def test_release_idempotency_is_scoped_to_the_campaign(organizer_user, ctf_event):
    # Two campaigns released with the SAME occurrence must not collapse onto one
    # intent: the idempotency identity is campaign-scoped (codex finding).
    _participant(ctf_event, "a@test.com")
    ws = _workspace_uuid(organizer_user)
    first_campaign = create_campaign(organizer_user, ws, _draft(ctf_event))
    second_campaign = create_campaign(organizer_user, ws, _draft(ctf_event, title="Second"))

    first = release_campaign(first_campaign, occurrence_key="shared-occ", actor_user_id=organizer_user.id)
    second = release_campaign(second_campaign, occurrence_key="shared-occ", actor_user_id=organizer_user.id)

    assert first.id != second.id
    assert first.campaign_id == first_campaign.id
    assert second.campaign_id == second_campaign.id


def test_release_rejects_a_revision_from_another_campaign(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    ws = _workspace_uuid(organizer_user)
    campaign = create_campaign(organizer_user, ws, _draft(ctf_event))
    other = create_campaign(organizer_user, ws, _draft(ctf_event, title="Other"))
    foreign_revision = other.message_revisions.first()

    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="x", revision=foreign_revision, actor_user_id=organizer_user.id)


def test_release_refuses_when_a_target_event_is_cancelled(organizer_user, ctf_event):
    from ctf.enums import EventStatus

    _participant(ctf_event, "a@test.com")
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event))
    CTFEvent.objects.filter(pk=ctf_event.pk).update(status=EventStatus.CANCELLED.value)

    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="x", actor_user_id=organizer_user.id)
