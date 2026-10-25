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
            cancel_campaign(campaign, actor=AdmissionActor(user_id=organizer_user.pk))
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


def test_concurrent_revisions_are_numbered_under_live_authority(organizer_user, ctf_event):
    from ctf.services.communication import revise_message

    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"})
    barrier = threading.Barrier(2)

    def revise(number):
        try:
            barrier.wait(timeout=10)
            return revise_message(
                campaign, subject=f"Revision {number}", body="Updated", actor=AdmissionActor(user_id=organizer_user.pk)
            ).revision_number
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers = list(pool.map(revise, [1, 2]))
    assert sorted(numbers) == [2, 3]
    assert campaign.message_revisions.count() == 3


def test_token_revocation_serializes_with_admission_and_denies_replay(organizer_user, ctf_event):
    from ctf.exceptions import CTFCommunicationError
    from shared.api_tokens.models import ApiToken

    _participants(ctf_event, 1)
    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"})
    token, _ = ApiToken.create_token(name="race", created_by=organizer_user, scopes=["ctf:communication:write"])
    actor = AdmissionActor(user_id=organizer_user.pk, token_id=token.pk)
    barrier = threading.Barrier(2)

    def release():
        try:
            barrier.wait(timeout=10)
            try:
                release_campaign(campaign, occurrence_key="race", admission=actor)
                return "released"
            except CTFCommunicationError:
                return "denied"
        finally:
            connection.close()

    def revoke():
        try:
            barrier.wait(timeout=10)
            ApiToken.objects.get(pk=token.pk).revoke()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        releasing = pool.submit(release)
        revoking = pool.submit(revoke)
        outcome = releasing.result(timeout=20)
        revoking.result(timeout=20)
    assert CommunicationIntent.objects.filter(campaign=campaign).count() == (1 if outcome == "released" else 0)
    with pytest.raises(CTFCommunicationError):
        release_campaign(campaign, occurrence_key="race", admission=actor)


def test_authority_audit_storage_failure_rolls_back_revision(organizer_user, ctf_event):
    from django.db import IntegrityError, transaction

    from ctf.services.communication import revise_message
    from shared.models import AuditLog

    campaign = _campaign(organizer_user, ctf_event, trigger_spec={"kind": "manual"})
    table = connection.ops.quote_name(AuditLog._meta.db_table)
    # A database constraint injects a real persistence failure. Existing evidence
    # remains intact; NOT VALID applies the constraint only to subsequent writes.
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT test_communication_audit_failure "
            "CHECK (context <> 'ctf_communication_authority') NOT VALID"
        )
    try:
        with pytest.raises(IntegrityError), transaction.atomic():
            revise_message(
                campaign, subject="No commit", body="No commit", actor=AdmissionActor(user_id=organizer_user.pk)
            )
        assert campaign.message_revisions.count() == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT test_communication_audit_failure")


def test_cutover_fence_rejects_old_binary_writes_and_claims(organizer_user, ctf_event):
    from django.db import IntegrityError, transaction

    from ctf.models import CTFNotification
    from ctf.services.communication.cutover import start_cutover

    task = CTFScheduledTask.objects.create(event=ctf_event, task_type="send_notification", scheduled_for=timezone.now())
    start_cutover(legacy_producers_stopped=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        CTFNotification.objects.create(
            event=ctf_event,
            created_by=organizer_user,
            notification_type="announcement",
            subject="No old writer",
            body="No send",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        CTFScheduledTask.objects.filter(pk=task.pk).update(status="running")
    task.refresh_from_db()
    assert task.status == "pending"


@pytest.mark.parametrize(
    "task_type", ["send_reminder", "cleanup_warning", "event_start", "event_end", "spin_up_ranges", "cleanup_ranges"]
)
def test_cutover_requires_versioned_claim_for_every_lifecycle_producer(ctf_event, task_type):
    from uuid import uuid4

    from django.db import IntegrityError, transaction

    from ctf.services.communication.cutover import activate_cutover, start_cutover

    task = CTFScheduledTask.objects.create(event=ctf_event, task_type=task_type, scheduled_for=timezone.now())
    start_cutover(legacy_producers_stopped=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        CTFScheduledTask.objects.filter(pk=task.pk).update(status="running", claim_token=uuid4())
    activate_cutover()
    with transaction.atomic():
        task.mark_running(claim_token=uuid4())
    task.refresh_from_db()
    assert task.status == "running"
    # Transaction-local ownership must not leak to an old claimant on this connection.
    with pytest.raises(IntegrityError), transaction.atomic():
        CTFScheduledTask.objects.filter(pk=task.pk).update(status="running", claim_token=uuid4())
