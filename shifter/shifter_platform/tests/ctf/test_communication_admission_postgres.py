"""PostgreSQL proofs for communication admission / scheduler races (#2099, AC4).

SQLite cannot prove ``select_for_update`` serialization, ``skip_locked`` claiming,
or the release/cancel lock ordering under real contention, so these run only on the
Postgres lane against real worker/database boundaries (mock only external
transports, ADR-019). They exercise: idempotent due-time release under a race, the
release-vs-cancel linearization (no duplicate/orphaned delivery), and the
scheduler's single-claim + completion fence under concurrent workers.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus, ScheduledTaskStatus, ScheduledTaskType
from ctf.enums_communication import DeliveryStatus, IntentStatus
from ctf.models import (
    CommunicationIntent,
    CTFParticipant,
    CTFScheduledTask,
    DeliveryAttempt,
    RecipientSnapshot,
)
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    cancel_campaign,
    create_campaign,
    release_campaign,
    release_due_declaration,
    schedule_declaration,
)

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
User = get_user_model()


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participants(event, count):
    for i in range(count):
        CTFParticipant.objects.create(
            event=event,
            email=f"p{i}@test.com",
            name=f"p{i}",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )


def _campaign(owner, event, *, trigger_spec, channels=("in_app",)):
    draft = CampaignDraft(
        title="Kickoff",
        origin="organizer_staff",
        target_event_ids=[event.id],
        audience_spec={"kind": "event", "event_ids": [str(event.id)]},
        trigger_spec=trigger_spec,
        channels=list(channels),
        subject="Welcome",
        body="Hello",
    )
    return create_campaign(owner, _workspace_uuid(owner), draft)


def test_concurrent_due_release_materializes_exactly_once(organizer_user, ctf_event):
    _participants(ctf_event, 3)
    due = timezone.now() - timezone.timedelta(minutes=1)  # due, within grace
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "absolute_time", "due_at": due.isoformat()})
    intent = schedule_declaration(
        campaign, due_at=due, occurrence_key="occ", actor=AdmissionActor(user_id=organizer_user.id)
    )

    barrier = threading.Barrier(2)
    outcomes: dict[int, str] = {}

    def worker(idx: int) -> None:
        barrier.wait(timeout=10)
        try:
            outcomes[idx] = release_due_declaration(intent, actor=AdmissionActor(user_id=organizer_user.id))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))

    # Both observe a released occurrence, but the audience is materialized exactly once.
    assert set(outcomes.values()) == {"released"}
    assert CommunicationIntent.objects.get(pk=intent.pk).status == IntentStatus.RELEASED.value
    assert RecipientSnapshot.objects.filter(intent=intent).count() == 3


def test_release_and_cancel_never_leave_deliverable_work(organizer_user, ctf_event):
    _participants(ctf_event, 4)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"})
    barrier = threading.Barrier(2)
    errors: dict[str, Exception] = {}

    def releaser() -> None:
        barrier.wait(timeout=10)
        try:
            release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
        except Exception as exc:  # a cancelled-first race legitimately refuses release
            errors["release"] = exc
        finally:
            connection.close()

    def canceller() -> None:
        barrier.wait(timeout=10)
        try:
            cancel_campaign(campaign)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (releaser, canceller)))

    # Whichever committed first, a cancelled campaign never leaves queued deliverable
    # work: either release refused (cancel won) or its queued work was then cancelled.
    campaign.refresh_from_db()
    assert campaign.status == "cancelled"
    assert not DeliveryAttempt.objects.filter(intent__campaign=campaign, status=DeliveryStatus.QUEUED.value).exists()


def test_release_and_participant_removal_leave_no_unfenced_delivery(organizer_user, ctf_event):
    from ctf.services.participant import delete_participant

    participant = CTFParticipant.objects.create(
        event=ctf_event,
        email="racer@test.com",
        name="racer",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"}, channels=("in_app", "email"))
    barrier = threading.Barrier(2)

    def releaser() -> None:
        barrier.wait(timeout=10)
        try:
            release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)
        finally:
            connection.close()

    def remover() -> None:
        barrier.wait(timeout=10)
        try:
            delete_participant(participant.pk)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (releaser, remover)))

    # The event lock serializes the two: either the participant was excluded before
    # release, or its snapshot was fenced after. No queued deliverable escapes.
    escaped = DeliveryAttempt.objects.filter(
        snapshot__participant_public_id=participant.id, status=DeliveryStatus.QUEUED.value
    )
    assert not escaped.exists()
    for snapshot in RecipientSnapshot.objects.filter(participant_public_id=participant.id):
        assert snapshot.delivery_coordinate == ""  # coordinate erased if a snapshot was captured


def test_concurrent_schedulers_never_double_claim_a_due_task(organizer_user, ctf_event):
    now = timezone.now()
    for _ in range(6):
        CTFScheduledTask.objects.create(
            event=ctf_event,
            task_type=ScheduledTaskType.EVENT_START.value,
            scheduled_for=now - timezone.timedelta(minutes=1),
            status=ScheduledTaskStatus.PENDING.value,
        )

    from ctf.management.commands.run_ctf_scheduler import Command

    barrier = threading.Barrier(2)
    claimed: dict[int, set] = {0: set(), 1: set()}

    def worker(idx: int) -> None:
        cmd = Command()
        barrier.wait(timeout=10)
        try:
            while True:
                got = cmd._claim_next_due()
                if got is None:
                    break
                claimed[idx].add(got[0].pk)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))

    assert not (claimed[0] & claimed[1])  # skip_locked: no task claimed by both
    assert claimed[0] | claimed[1] == set(CTFScheduledTask.objects.values_list("pk", flat=True))


def test_real_cancellation_path_and_completion_are_mutually_exclusive(organizer_user, ctf_event):
    """A real cancellation path (_cancel_event_tasks) and a claiming worker cannot
    both win: completion is never overwritten by a blind cancel, and a cancel is
    never overwritten by a fenced completion (#2099 claim-fence contract)."""
    from ctf.management.commands.run_ctf_scheduler import Command
    from ctf.services.event.scheduling import _cancel_event_tasks

    CTFScheduledTask.objects.create(
        event=ctf_event,
        task_type=ScheduledTaskType.EVENT_START.value,
        scheduled_for=timezone.now() - timezone.timedelta(minutes=1),
        status=ScheduledTaskStatus.PENDING.value,
    )
    barrier = threading.Barrier(2)
    worker_completed: dict[str, bool | None] = {}

    def worker() -> None:
        cmd = Command()
        barrier.wait(timeout=10)
        try:
            claimed = cmd._claim_next_due()
            worker_completed["done"] = claimed[0].complete_if_claimed(claimed[1]) if claimed else None
        finally:
            connection.close()

    def canceller() -> None:
        barrier.wait(timeout=10)
        try:
            _cancel_event_tasks(ctf_event)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (worker, canceller)))

    task = CTFScheduledTask.objects.get(event=ctf_event, task_type=ScheduledTaskType.EVENT_START.value)
    assert task.status in (ScheduledTaskStatus.COMPLETED.value, ScheduledTaskStatus.CANCELLED.value)
    if worker_completed.get("done"):
        assert task.status == ScheduledTaskStatus.COMPLETED.value  # completion not overwritten by cancel
    else:
        assert task.status == ScheduledTaskStatus.CANCELLED.value  # cancel won; completion was fenced


def test_reclaimed_task_fences_the_stale_worker_completion(organizer_user, ctf_event):
    task = CTFScheduledTask.objects.create(
        event=ctf_event,
        task_type=ScheduledTaskType.EVENT_START.value,
        scheduled_for=timezone.now(),
        status=ScheduledTaskStatus.RUNNING.value,
    )
    token_a = uuid4()
    CTFScheduledTask.objects.filter(pk=task.pk).update(claim_token=token_a)

    # A stalls; recovery reclaims with a new token.
    token_b = uuid4()
    CTFScheduledTask.objects.filter(pk=task.pk).update(claim_token=token_b)

    # A wakes and tries to complete with its dead token: fenced. B completes.
    assert task.complete_if_claimed(token_a) is False
    assert task.complete_if_claimed(token_b) is True
    task.refresh_from_db()
    assert task.status == ScheduledTaskStatus.COMPLETED.value
