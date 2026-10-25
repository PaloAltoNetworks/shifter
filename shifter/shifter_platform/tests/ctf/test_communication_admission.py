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


def test_service_target_list_is_bounded_before_deduplication(organizer_user, ctf_event):
    import workspaces.services as ws
    from ctf.services.communication import CampaignDraft, create_campaign

    with pytest.raises(CTFCommunicationError):
        create_campaign(
            organizer_user,
            ws.resolve_personal_workspace(organizer_user).workspace_uuid,
            CampaignDraft(
                title="Bounded",
                origin="organizer_staff",
                target_event_ids=[ctf_event.pk] * 101,
                audience_spec={"kind": "event", "event_ids": [str(ctf_event.pk)]},
                trigger_spec={"kind": "manual"},
                channels=["in_app"],
                subject="Hello",
                body="Rules",
            ),
        )


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


def test_release_accepts_live_exact_scope_token_owner_pair(organizer_user, ctf_event):
    from shared.api_tokens.models import ApiToken

    campaign = _campaign(organizer_user, ctf_event)
    token, _ = ApiToken.create_token(
        name="communication",
        created_by=organizer_user,
        scopes=["ctf:communication:write"],
    )
    actor = AdmissionActor(user_id=organizer_user.pk, token_id=token.pk)
    intent = release_campaign(campaign, occurrence_key="token-occ", admission=actor)
    assert intent.status == "released"
    assert intent.actor_user_id == organizer_user.pk
    assert intent.actor_token_id == token.pk


@pytest.mark.parametrize(
    "denial", ["scope", "revoked", "expired", "missing_owner", "wrong_owner", "inactive", "deleted", "temporary"]
)
def test_token_release_rechecks_live_owner_and_scope(organizer_user, ctf_event, denial):
    from datetime import timedelta

    from management.services import get_user_profile
    from shared.api_tokens.models import ApiToken

    campaign = _campaign(organizer_user, ctf_event)
    scopes = ["ctf:communication:read", "ctf:event:write"] if denial == "scope" else ["ctf:communication:write"]
    expiry = timezone.now() + timedelta(seconds=-1 if denial == "expired" else 3600)
    token, _ = ApiToken.create_token(
        name="communication",
        created_by=organizer_user,
        scopes=scopes,
        expires_at=expiry,
    )
    actor_user = organizer_user
    if denial == "revoked":
        token.revoke()
    elif denial == "missing_owner":
        # Owner deletion's SET_NULL transition is permitted; transfer is not.
        ApiToken.objects.filter(pk=token.pk).update(created_by=None)
    elif denial == "wrong_owner":
        actor_user = User.objects.create_user(username="other-owner")
    elif denial == "inactive":
        User.objects.filter(pk=organizer_user.pk).update(is_active=False)
    elif denial in {"deleted", "temporary"}:
        profile = get_user_profile(organizer_user)
        if denial == "deleted":
            profile.deleted_at = timezone.now()
        else:
            profile.is_ctf_account = True
            profile.user_type = "ctf_participant"
        profile.save()
    with pytest.raises(CTFCommunicationError):
        release_campaign(
            campaign, occurrence_key="token-occ", admission=AdmissionActor(user_id=actor_user.pk, token_id=token.pk)
        )
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()


@pytest.mark.parametrize("operation", ["revise", "cancel"])
def test_campaign_mutations_require_live_actor(organizer_user, ctf_event, operation):
    from ctf.services.communication import cancel_campaign, revise_message

    campaign = _campaign(organizer_user, ctf_event)
    outsider = User.objects.create_user(username="outsider")
    actor = AdmissionActor(user_id=outsider.pk)
    with pytest.raises(CTFCommunicationError):
        if operation == "revise":
            revise_message(campaign, subject="Changed", body="Changed", actor=actor)
        else:
            cancel_campaign(campaign, actor=actor)
    campaign.refresh_from_db()
    assert campaign.status == "draft"
    assert campaign.message_revisions.count() == 1


def test_revision_rechecks_persisted_campaign_status(organizer_user, ctf_event):
    from ctf.models import CommunicationCampaign
    from ctf.services.communication import revise_message

    campaign = _campaign(organizer_user, ctf_event)
    CommunicationCampaign.objects.filter(pk=campaign.pk).update(status="cancelled")
    with pytest.raises(CTFCommunicationError):
        revise_message(campaign, subject="Changed", body="Changed", actor=AdmissionActor(user_id=organizer_user.pk))
    assert campaign.message_revisions.count() == 1


def test_each_target_authority_is_retained_without_content(organizer_user, ctf_event):
    from shared.models import AuditLog

    campaign = _campaign(organizer_user, ctf_event)
    release_campaign(campaign, occurrence_key="audited", actor_user_id=organizer_user.pk)
    evidence = AuditLog.objects.filter(context="ctf_communication_authority").latest("timestamp")
    assert evidence.new_state["event_id"] == str(ctf_event.pk)
    assert evidence.new_state["authority_source"] == "owner"
    assert "Hello" not in str(evidence.new_state)


def test_scheduled_token_revalidates_original_owner(organizer_user, ctf_event):
    from django.db import IntegrityError, ProgrammingError, transaction

    from ctf.models import CTFScheduledTask, RecipientSnapshot
    from ctf.services.communication import run_release_communication_task, schedule_declaration
    from shared.api_tokens.models import ApiToken

    campaign = _campaign(organizer_user, ctf_event)
    due = timezone.now() - timezone.timedelta(seconds=1)
    # Draft triggers are immutable through the service; construct the timed draft
    # before admission rather than treating task metadata as authority.
    campaign.trigger_spec = {"kind": "absolute_time", "due_at": due.isoformat()}
    campaign.save(update_fields=["trigger_spec"])
    token, _ = ApiToken.create_token(name="scheduled", created_by=organizer_user, scopes=["ctf:communication:write"])
    intent = schedule_declaration(
        campaign, due_at=due, occurrence_key="timed", actor=AdmissionActor(user_id=organizer_user.pk, token_id=token.pk)
    )
    task = CTFScheduledTask.objects.get(metadata__intent_id=str(intent.pk))
    other = User.objects.create_user(username="replacement-owner")
    with pytest.raises((IntegrityError, ProgrammingError)), transaction.atomic():
        ApiToken.objects.filter(pk=token.pk).update(created_by=other)
    User.objects.filter(pk=organizer_user.pk).update(is_active=False)
    assert run_release_communication_task(task)["outcome"] == "denied"
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()


def test_deleted_target_never_reduces_campaign_authorization_scope(organizer_user, ctf_event):
    from ctf.models import CTFEvent

    campaign = _campaign(organizer_user, ctf_event)
    CTFEvent.all_objects.filter(pk=ctf_event.pk).update(deleted_at=timezone.now())
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="deleted", actor_user_id=organizer_user.pk)
    assert not CommunicationIntent.objects.filter(campaign=campaign).exists()
