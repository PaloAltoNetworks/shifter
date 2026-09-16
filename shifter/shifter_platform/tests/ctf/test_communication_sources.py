"""Trigger-source realizability at the admission seam (#2099, CTF-010).

Every trigger source enters the one admission transaction. Sources whose
realization is not available in this slice — RAES shared/script-time occurrences
and range signals, which require a RAES interpreter / CMS generation projection
that is provisioning-only at this baseline — are fail-closed rather than
approximated (ADR-051-R12). Manual, absolute-time, and event-lifecycle sources are
realizable now.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationIntent, CTFParticipant
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    create_campaign,
    release_campaign,
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


@pytest.mark.parametrize(
    "trigger_spec",
    [
        {"kind": "range_signal", "declaration_ref": "decl-1"},
        {"kind": "raes_occurrence", "declaration_ref": "decl-1", "occurrence_ref": "occ-1"},
    ],
)
def test_release_is_fail_closed_for_unsupported_sources(organizer_user, ctf_event, trigger_spec):
    campaign = _campaign(organizer_user, ctf_event, trigger_spec=trigger_spec)

    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_schedule_is_fail_closed_for_unsupported_sources(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "range_signal", "declaration_ref": "d"})

    due = timezone.now() + timezone.timedelta(hours=1)
    actor = AdmissionActor(user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError):
        schedule_declaration(campaign, due_at=due, occurrence_key="occ", actor=actor)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_manual_source_is_realizable(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"})
    intent = release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
    assert intent.status == "released"


def test_absolute_time_source_is_realizable(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=1)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": due.isoformat()})
    intent = schedule_declaration(
        campaign, due_at=due, occurrence_key="occ", actor=AdmissionActor(user_id=organizer_user.id)
    )
    assert intent.status == "scheduled"
