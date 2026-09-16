"""Occurrence enforcement and replay-meaning conflicts at admission (#2099, AC1).

A supported trigger *kind* is not enough: the declared *occurrence* must actually
have happened before any audience is materialized, and a same-key replay must
carry the same immutable declaration meaning or be rejected. Regression coverage
for the codex review findings on release.py / scheduling.py / admission.py.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import EventStatus, ParticipantStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationIntent, CTFEvent, CTFParticipant, MessageRevision
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    create_campaign,
    release_campaign,
    revise_message,
    schedule_declaration,
)

pytestmark = pytest.mark.django_db


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _campaign(organizer_user, ctf_event, *, trigger_spec):
    CTFParticipant.objects.create(
        event=ctf_event,
        email="a@test.com",
        name="a",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    return create_campaign(
        organizer_user,
        _workspace_uuid(organizer_user),
        CampaignDraft(
            title="Kickoff",
            origin="organizer_staff",
            target_event_ids=[ctf_event.id],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
            trigger_spec=trigger_spec,
            channels=["in_app"],
            subject="Welcome",
            body="Hello",
        ),
    )


# --- Occurrence enforcement (Fix 3) -------------------------------------------


def test_future_absolute_time_cannot_be_released_immediately(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": due.isoformat()})

    # A future timed occurrence has not happened; immediate release is rejected.
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_schedule_due_time_must_match_the_trigger(organizer_user, ctf_event):
    trigger_due = timezone.now() + timezone.timedelta(hours=6)
    campaign = _campaign(
        organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": trigger_due.isoformat()}
    )

    mismatched_due = trigger_due + timezone.timedelta(hours=1)  # diverges from the authored trigger
    actor = AdmissionActor(user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError):
        schedule_declaration(campaign, due_at=mismatched_due, occurrence_key="occ", actor=actor)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_event_lifecycle_immediate_release_requires_the_milestone(organizer_user, ctf_event):
    CTFEvent.objects.filter(pk=ctf_event.pk).update(status=EventStatus.REGISTRATION.value)
    ctf_event.refresh_from_db()
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "event_lifecycle", "event_status": "active"})

    # The event has not reached 'active': the milestone has not occurred.
    system_actor = AdmissionActor(system=True)
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", admission=system_actor)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()

    # Once the milestone is reached, the system release is admitted.
    CTFEvent.objects.filter(pk=ctf_event.pk).update(status=EventStatus.ACTIVE.value)
    intent = release_campaign(campaign, occurrence_key="occ", admission=AdmissionActor(system=True))
    assert intent.status == "released"


def test_event_lifecycle_is_not_clock_schedulable(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "event_lifecycle", "event_status": "active"})
    due = timezone.now() + timezone.timedelta(hours=1)
    system_actor = AdmissionActor(system=True)
    with pytest.raises(CTFCommunicationError):
        schedule_declaration(campaign, due_at=due, occurrence_key="occ", actor=system_actor)


# --- Replay meaning (Fix 4) ---------------------------------------------------


def test_identical_schedule_replay_collapses(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": due.isoformat()})
    a = schedule_declaration(
        campaign, due_at=due, occurrence_key="occ", actor=AdmissionActor(user_id=organizer_user.id)
    )
    b = schedule_declaration(
        campaign, due_at=due, occurrence_key="occ", actor=AdmissionActor(user_id=organizer_user.id)
    )
    assert a.id == b.id
    assert CommunicationIntent.objects.filter(campaign=campaign).count() == 1


def test_conflicting_schedule_replay_is_rejected(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": due.isoformat()})
    schedule_declaration(campaign, due_at=due, occurrence_key="occ", actor=AdmissionActor(user_id=organizer_user.id))
    revised = revise_message(campaign, subject="New", body="Changed")

    # Same occurrence key, different explicit revision -> conflicting meaning, rejected.
    actor = AdmissionActor(user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError):
        schedule_declaration(campaign, due_at=due, occurrence_key="occ", actor=actor, revision=revised)
    # The original declaration is unchanged (still the first revision, one intent).
    assert CommunicationIntent.objects.filter(campaign=campaign).count() == 1
    intent = CommunicationIntent.objects.get(campaign=campaign)
    assert intent.revision_id == MessageRevision.objects.filter(campaign=campaign).earliest("revision_number").pk
