"""Scheduled communication declarations and due-time release (#2099, CTF-010).

A scheduled declaration commits the intent and its release task together and does
NOT materialize an audience; release happens only at the eligible occurrence,
under the same admission re-check and a closed lateness/expiry policy. Repeated
ticks and restarts are idempotent. Each test drives the real services.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus, ScheduledTaskStatus, ScheduledTaskType
from ctf.enums_communication import IntentStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import (
    CommunicationIntent,
    CTFParticipant,
    CTFScheduledTask,
    RecipientSnapshot,
)
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    create_campaign,
    release_due_declaration,
    request_early_release,
    run_release_communication_task,
    schedule_declaration,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _scheduled(organizer_user, ctf_event, *, due_at, occurrence="occ-sched"):
    CTFParticipant.objects.create(
        event=ctf_event,
        email="a@test.com",
        name="a",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    campaign = create_campaign(
        organizer_user,
        _workspace_uuid(organizer_user),
        CampaignDraft(
            title="Kickoff",
            origin="organizer_staff",
            target_event_ids=[ctf_event.id],
            audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
            trigger_spec={"kind": "absolute_time", "due_at": due_at.isoformat()},
            channels=["in_app"],
            subject="Welcome",
            body="Hello",
        ),
    )
    intent = schedule_declaration(
        campaign,
        due_at=due_at,
        occurrence_key=occurrence,
        actor=AdmissionActor(user_id=organizer_user.id),
    )
    return campaign, intent


def test_schedule_commits_a_scheduled_intent_and_task_without_materializing(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)

    assert intent.status == IntentStatus.SCHEDULED.value
    assert intent.due_at == due
    # No audience materialized at scheduling: future content is never inbox-visible.
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)
    assert task.scheduled_for == due
    assert task.metadata["intent_id"] == str(intent.id)
    assert task.status == ScheduledTaskStatus.PENDING.value


def test_due_release_materializes_and_is_idempotent(organizer_user, ctf_event):
    due = timezone.now() - timezone.timedelta(minutes=1)  # due, within grace
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)

    first = release_due_declaration(intent, actor=AdmissionActor(user_id=organizer_user.id))
    assert first == "released"
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.RELEASED.value
    assert RecipientSnapshot.objects.filter(intent=intent).count() == 1

    # A repeated tick/restart observes the release; it does not re-materialize.
    second = release_due_declaration(intent, actor=AdmissionActor(user_id=organizer_user.id))
    assert second == "released"
    assert RecipientSnapshot.objects.filter(intent=intent).count() == 1


def test_release_expires_past_the_grace_window(organizer_user, ctf_event, settings):
    settings.CTF_COMMUNICATION_RELEASE_GRACE_MINUTES = 20
    due = timezone.now() - timezone.timedelta(minutes=45)  # well past grace
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)

    outcome = release_due_declaration(intent, actor=AdmissionActor(user_id=organizer_user.id))

    assert outcome == "expired"
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.EXPIRED.value
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()  # durable no-work


def test_due_release_revalidates_and_denies_a_revoked_actor(organizer_user, ctf_event):
    due = timezone.now() - timezone.timedelta(minutes=1)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)

    User.objects.filter(pk=organizer_user.id).update(is_active=False)  # authority revoked before due

    actor = AdmissionActor(user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError):
        release_due_declaration(intent, actor=actor)
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.SCHEDULED.value
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()


def test_scheduler_handler_reschedules_when_not_yet_due(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)  # future
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)

    result = run_release_communication_task(task)

    assert result["reschedule_for"] == due
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()


def test_run_task_now_early_releases_a_scheduled_communication(organizer_user, ctf_event):
    from ctf.enums import ScheduledTaskStatus
    from ctf.services.event.scheduling import run_task_now

    due = timezone.now() + timezone.timedelta(hours=6)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)

    run_task_now(ctf_event.id, task.id, actor_id=organizer_user.id)

    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.RELEASED.value
    assert RecipientSnapshot.objects.filter(intent=intent).count() == 1
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.COMPLETED.value


def test_run_task_now_denies_comm_early_release_without_notification_authority(organizer_user, ctf_event):
    from ctf.services.event.scheduling import run_task_now

    due = timezone.now() + timezone.timedelta(hours=6)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)
    outsider = User.objects.create_user(username="outsider", password="pw")  # nosec B106

    with pytest.raises(CTFCommunicationError):
        run_task_now(ctf_event.id, task.id, actor_id=outsider.id)
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.SCHEDULED.value


def test_early_release_before_due_requires_the_grant(organizer_user, ctf_event):
    due = timezone.now() + timezone.timedelta(hours=6)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)

    # Without the explicit early-release grant, an early release is denied.
    ungranted_actor = AdmissionActor(user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError):
        request_early_release(intent, actor=ungranted_actor)
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.SCHEDULED.value

    # With the grant, an authorized organizer run-now releases before the due time.
    outcome = request_early_release(intent, actor=AdmissionActor(user_id=organizer_user.id, allow_early_release=True))
    assert outcome == "released"
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.RELEASED.value
    assert RecipientSnapshot.objects.filter(intent=intent).count() == 1


def test_transient_backpressure_reschedules_and_keeps_the_occurrence(organizer_user, ctf_event, monkeypatch):
    from ctf.services.communication import release as release_module

    due = timezone.now() - timezone.timedelta(minutes=1)  # due, within grace
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)

    def _pressure(_request):
        raise CTFCommunicationError("busy", code="CTF_COMMUNICATION_RATE_LIMITED")

    monkeypatch.setattr(release_module, "enforce_admission", _pressure)
    result = run_release_communication_task(task)

    # Transient pressure reschedules a retry; the occurrence is NOT discarded.
    assert "reschedule_for" in result
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.SCHEDULED.value
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()


def test_permanent_denial_at_due_time_expires_the_declaration(organizer_user, ctf_event):
    due = timezone.now() - timezone.timedelta(minutes=1)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)
    User.objects.filter(pk=organizer_user.id).update(is_active=False)  # authority permanently revoked

    result = run_release_communication_task(task)

    # A permanent denial reaches a terminal no-work outcome, not a stranded SCHEDULED.
    assert result["outcome"] == "denied"
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.EXPIRED.value
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()


def test_run_task_now_denies_token_authored_early_release(organizer_user, ctf_event):
    from ctf.services.event.scheduling import run_task_now

    due = timezone.now() + timezone.timedelta(hours=6)
    _campaign, intent = _scheduled(organizer_user, ctf_event, due_at=due)
    task = CTFScheduledTask.objects.get(task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value)

    # A token-authenticated run-now (owner id + token id) must be denied: token
    # communication is fail-closed, and its owner cannot enter the session path.
    with pytest.raises(CTFCommunicationError):
        run_task_now(ctf_event.id, task.id, actor_id=organizer_user.id, actor_token_id=4321)
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.SCHEDULED.value
    assert not RecipientSnapshot.objects.filter(intent=intent).exists()
