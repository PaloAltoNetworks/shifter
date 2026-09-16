"""PostgreSQL proofs for the delivery engine's concurrency and recovery (#2098).

SQLite cannot prove ``select_for_update(skip_locked=True)`` semantics, lease
fencing under contention, or fair batching against real row locks, so these run
only on the Postgres lane. They exercise the real worker/database boundary per the
issue's acceptance criteria (mock only external transports, ADR-019).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import EventStatus, ParticipantStatus
from ctf.enums_communication import DeliveryStatus
from ctf.models import CTFEvent, CTFParticipant, DeliveryAttempt
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign
from ctf.services.communication import delivery as delivery_svc

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
User = get_user_model()


def _event(owner, name):
    return CTFEvent.objects.create(
        name=name,
        created_by=owner,
        workspace_id=workspace_services.resolve_personal_workspace(owner).workspace_id,
        status=EventStatus.REGISTRATION.value,
        event_start=timezone.now() + timezone.timedelta(days=1),
        event_end=timezone.now() + timezone.timedelta(days=1, hours=8),
        scenario_id="basic",
        participant_password_override="pw-test",  # nosec B106
    )


def _participants(event, count):
    for i in range(count):
        CTFParticipant.objects.create(
            event=event,
            email=f"p{i}@test.com",
            name=f"p{i}",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )


def _release(owner, event, count, *, occurrence="occ"):
    _participants(event, count)
    draft = CampaignDraft(
        title="Kickoff",
        origin="organizer_staff",
        target_event_ids=[event.id],
        audience_spec={"kind": "event", "event_ids": [str(event.id)]},
        trigger_spec={"kind": "manual"},
        channels=["in_app"],
        subject="Welcome",
        body="See the [rules](/rules).",
    )
    workspace_uuid = str(workspace_services.resolve_personal_workspace(owner).workspace_uuid)
    campaign = create_campaign(owner, workspace_uuid, draft)
    return release_campaign(campaign, occurrence_key=occurrence, actor_user_id=owner.id)


def test_concurrent_workers_never_double_claim_a_command(organizer_user, ctf_event):
    _release(organizer_user, ctf_event, 6)
    cfg = delivery_svc.WorkerConfig.from_settings()
    barrier = threading.Barrier(2)
    results: dict[int, list] = {}

    def worker(idx: int) -> None:
        barrier.wait(timeout=10)
        try:
            results[idx] = [a.pk for a in delivery_svc.claim_batch(cfg, now=timezone.now())]
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))

    a, b = set(results[0]), set(results[1])
    assert not (a & b)  # skip_locked: no command is claimed by both workers
    assert a | b == set(DeliveryAttempt.objects.values_list("pk", flat=True))  # together they claim all


def test_fair_batches_do_not_let_one_event_monopolize(organizer_user, ctf_event, settings):
    settings.CTF_COMMUNICATION_WORKER_PER_EVENT_CAP = 3
    busy = _event(organizer_user, "Busy")
    _release(organizer_user, busy, 10, occurrence="busy")
    _release(organizer_user, ctf_event, 2, occurrence="quiet")

    claimed = delivery_svc.claim_batch(delivery_svc.WorkerConfig.from_settings(), now=timezone.now())

    claimed_events = {DeliveryAttempt.objects.get(pk=a.pk).snapshot.event_id for a in claimed}
    # Neither event is starved: both are represented in the claimed batch.
    assert busy.id in claimed_events
    assert ctf_event.id in claimed_events
    per_event = {}
    for a in claimed:
        eid = DeliveryAttempt.objects.get(pk=a.pk).snapshot.event_id
        per_event[eid] = per_event.get(eid, 0) + 1
    assert per_event[busy.id] <= 3  # per-event cap holds


def test_reclaimed_lease_fences_the_stale_worker(organizer_user, ctf_event):
    _release(organizer_user, ctf_event, 1)
    cfg = delivery_svc.WorkerConfig.from_settings()
    stale = delivery_svc.claim_batch(cfg, now=timezone.now())[0]  # worker A, token A (in memory)

    # A stalls; its lease expires and worker B reclaims the command with a new token.
    DeliveryAttempt.objects.filter(pk=stale.pk).update(lease_expires_at=timezone.now() - timezone.timedelta(minutes=5))
    reclaimed = delivery_svc.claim_batch(cfg, now=timezone.now())[0]
    assert reclaimed.lease_token != stale.lease_token

    # A wakes and tries to settle with its dead token: fenced (ignored).
    assert delivery_svc.process_attempt(stale, cfg) == "stale"
    # B settles normally.
    assert delivery_svc.process_attempt(reclaimed, cfg) == DeliveryStatus.ACCEPTED.value

    final = DeliveryAttempt.objects.get(pk=stale.pk)
    assert final.status == DeliveryStatus.ACCEPTED.value  # exactly one terminal outcome, from B
