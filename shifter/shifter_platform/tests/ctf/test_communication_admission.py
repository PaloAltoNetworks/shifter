"""Live re-authorization at communication admission (#2099, CTF-010).

Release is the one admission transaction: it re-derives authority server-side and
re-checks it against the live actor/token/workspace/event inside the locked
transaction, so a revoked actor, an unauthorized actor, or any token-authored
declaration admits no new work (AC3). Token scopes are slice 3, so token-authored
communication is fail-closed here. Each test drives the real service and asserts
the effect.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationIntent, CTFParticipant
from ctf.services.communication import AdmissionActor, CampaignDraft, create_campaign, release_campaign

pytestmark = pytest.mark.django_db
User = get_user_model()


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _campaign(organizer_user, ctf_event):
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
            trigger_spec={"kind": "manual"},
            channels=["in_app"],
            subject="Welcome",
            body="Hello",
        ),
    )


def test_release_denies_an_actor_without_notification_authority(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event)
    outsider = User.objects.create_user(username="outsider", password="pw")  # nosec B106

    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", actor_user_id=outsider.id)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_release_denies_a_revoked_actor(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event)
    User.objects.filter(pk=organizer_user.id).update(is_active=False)

    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_release_is_fail_closed_for_token_authored_declarations(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event)

    # The exact ctf:communication scope surface is slice 3; any token-authored
    # release is denied here rather than substituting another scope.
    token_actor = AdmissionActor(token_id=4321)
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", admission=token_actor)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


def test_system_authored_release_is_admitted(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event)

    # Trusted lifecycle/lease automation admits without a live human actor, but only
    # when system authority is explicitly declared (a missing actor is not enough).
    intent = release_campaign(campaign, occurrence_key="occ", admission=AdmissionActor(system=True))
    assert intent.status == "released"


def test_release_requires_an_explicit_actor(organizer_user, ctf_event):
    campaign = _campaign(organizer_user, ctf_event)

    # No user, no token, no declared system authority: a missing actor is never
    # implicit system authority.
    no_actor = AdmissionActor()
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="occ", admission=no_actor)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()
