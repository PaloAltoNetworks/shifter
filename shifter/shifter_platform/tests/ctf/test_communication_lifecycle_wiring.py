"""Communication lifecycle fencing is wired through the owning services (#2099).

The four communication hooks must fire from the services that own the durable
mutation — event cancellation, participant removal — not only from direct hook
tests (AC3). These drive the real owning service and assert the communication
effect, so the wiring goes red if it is removed.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.enums_communication import DeliveryStatus, IntentStatus
from ctf.models import (
    CommunicationIntent,
    CTFParticipant,
    DeliveryAttempt,
    RecipientSnapshot,
)
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    create_campaign,
    release_campaign,
    schedule_declaration,
)
from ctf.services.event import cancel_event
from ctf.services.participant import delete_participant

pytestmark = pytest.mark.django_db


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participant(event, email="a@test.com"):
    return CTFParticipant.objects.create(
        event=event,
        email=email,
        name=email.split("@")[0],
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


def _campaign(organizer_user, ctf_event, *, channels=("in_app",)):
    return create_campaign(
        organizer_user,
        _workspace_uuid(organizer_user),
        CampaignDraft(
            title="Kickoff",
            origin="organizer_staff",
            target_event_ids=[ctf_event.id],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
            trigger_spec={"kind": "manual"},
            channels=list(channels),
            subject="Welcome",
            body="Hello",
        ),
    )


def test_cancel_event_fences_scheduled_and_stops_unclaimed_communications(organizer_user, ctf_event):
    _participant(ctf_event)
    # A released campaign with queued (unclaimed) delivery work...
    released_campaign = _campaign(organizer_user, ctf_event)
    released = release_campaign(released_campaign, occurrence_key="rel", actor_user_id=organizer_user.id)
    # ...and a separate scheduled declaration awaiting its due time.
    scheduled_campaign = _campaign(organizer_user, ctf_event)
    scheduled = schedule_declaration(
        scheduled_campaign,
        due_at=timezone.now() + timezone.timedelta(hours=6),
        occurrence_key="sched",
        actor=AdmissionActor(user_id=organizer_user.id),
    )

    assert cancel_event(ctf_event) is True

    # The owning cancel path fenced the scheduled intent and stopped unclaimed work.
    assert CommunicationIntent.objects.get(pk=scheduled.pk).status == IntentStatus.FENCED.value
    assert not DeliveryAttempt.objects.filter(intent=released, status=DeliveryStatus.QUEUED.value).exists()


def test_account_purge_erases_coordinate_and_stops_unclaimed_communications(organizer_user, settings):
    from datetime import timedelta

    from django.contrib.auth import get_user_model

    from ctf.enums import EventStatus
    from ctf.models import CTFEvent
    from ctf.services.participant.accounts import purge_expired_participant_accounts

    settings.CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS = 24
    user_model = get_user_model()
    # An ended, past-retention event whose participant is a CTF account marked for purge.
    event = CTFEvent.objects.create(
        name="Ended",
        created_by=organizer_user,
        workspace_id=workspace_services.resolve_personal_workspace(organizer_user).workspace_id,
        status=EventStatus.ENDED.value,
        event_start=timezone.now() - timedelta(days=3),
        event_end=timezone.now() - timedelta(days=2),
        scenario_id="basic",
        participant_password_override="pw-test",  # nosec B106
    )
    account = user_model.objects.create_user(username="p-purge", email="purge@test.com", password="pw")  # nosec B106
    profile = account.profile
    profile.is_ctf_account = True
    profile.user_type = "ctf_participant"
    profile.save()
    participant = CTFParticipant.objects.create(
        event=event,
        user=account,
        email="purge@test.com",
        name="purge",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    campaign = _campaign(organizer_user, event, channels=("in_app", "email"))
    intent = release_campaign(campaign, occurrence_key="rel", actor_user_id=organizer_user.id)
    snapshot = RecipientSnapshot.objects.get(intent=intent, participant_public_id=participant.id)

    purge_expired_participant_accounts()

    snapshot.refresh_from_db()
    assert snapshot.delivery_coordinate == ""
    assert not DeliveryAttempt.objects.filter(snapshot=snapshot, status=DeliveryStatus.QUEUED.value).exists()


def test_delete_participant_erases_coordinate_and_stops_unclaimed_communications(organizer_user, ctf_event):
    participant = _participant(ctf_event)
    campaign = _campaign(organizer_user, ctf_event, channels=("in_app", "email"))
    intent = release_campaign(campaign, occurrence_key="rel", actor_user_id=organizer_user.id)
    snapshot = RecipientSnapshot.objects.get(intent=intent)

    assert delete_participant(participant.pk) is True

    snapshot.refresh_from_db()
    assert snapshot.delivery_coordinate == ""  # coordinate erased, identity retained as evidence
    assert not DeliveryAttempt.objects.filter(snapshot=snapshot, status=DeliveryStatus.QUEUED.value).exists()


def test_account_purge_rolls_back_anonymization_if_the_fence_fails(organizer_user, settings, monkeypatch):
    """Anonymize and its communication fence commit together: if the fence raises,
    the account is NOT left anonymized (and thus skipped by the next sweep)."""
    from datetime import timedelta

    from django.contrib.auth import get_user_model

    import ctf.services.communication as comm
    from ctf.enums import EventStatus
    from ctf.models import CTFEvent
    from ctf.services.participant.accounts import purge_expired_participant_accounts

    settings.CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS = 24
    account = get_user_model().objects.create_user(username="p-rb", email="rb@test.com", password="pw")  # nosec B106
    profile = account.profile
    profile.is_ctf_account = True
    profile.user_type = "ctf_participant"
    profile.save()
    event = CTFEvent.objects.create(
        name="Ended",
        created_by=organizer_user,
        workspace_id=workspace_services.resolve_personal_workspace(organizer_user).workspace_id,
        status=EventStatus.ENDED.value,
        event_start=timezone.now() - timedelta(days=3),
        event_end=timezone.now() - timedelta(days=2),
        scenario_id="basic",
        participant_password_override="pw-test",  # nosec B106
    )
    CTFParticipant.objects.create(
        event=event,
        user=account,
        email="rb@test.com",
        name="rb",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )

    def _boom(_participant):
        raise RuntimeError("fence failure")

    monkeypatch.setattr(comm, "on_participant_removed", _boom)
    with pytest.raises(RuntimeError):
        purge_expired_participant_accounts()

    # Anonymization was rolled back with the failed fence: the account is intact.
    account.refresh_from_db()
    assert account.profile.anonymized_at is None
    assert account.is_active is True
