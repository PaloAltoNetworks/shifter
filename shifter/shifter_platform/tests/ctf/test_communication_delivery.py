"""Delivery engine: worker claim/lease/fence/retry, in-app channel, and metrics.

Covers issue #2098 (CTF-008): the lease-based delivery worker consuming the #2048
``DeliveryAttempt`` outbox, the in-app channel as a durable inbox with a
reference-only WebSocket wake-up on a stable identity, and fail-soft metrics. These
are SQLite-lane unit tests (the coverage publisher); real-boundary concurrency and
recovery live in ``test_communication_delivery_postgres.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.enums_communication import DeliveryStatus
from ctf.models import CTFParticipant, DeliveryAttempt, ParticipantReceipt, RecipientSnapshot
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign
from ctf.services.communication import delivery as delivery_svc
from ctf.services.communication.adapters import contract as adapter_contract
from ctf.services.communication.adapters import register_adapter
from ctf.services.communication.adapters.contract import DeliveryOutcome, OutcomeClass
from ctf.services.notification.realtime import publish_communication_wakeup
from shared.models import WebSocketNotification

pytestmark = pytest.mark.django_db

User = get_user_model()


class _NullPublisher:
    """A put_metric_data-compatible sink so metrics emit runs real logic off the cloud."""

    def put_metric_data(self, **kwargs: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _hermetic_metrics(monkeypatch):
    """Keep the worker's metrics emission off the real cloud (ADR-019: mock the transport)."""
    monkeypatch.setattr("ctf.services.communication.metrics._resolve_client", lambda: _NullPublisher())


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participant(event, email, *, user=None, status=ParticipantStatus.ACTIVE.value):
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=email,
        name=email.split("@")[0],
        status=status,
        registered_at=timezone.now(),
    )


def _draft(ctf_event, *, channels=("in_app", "email"), **overrides) -> CampaignDraft:
    data = {
        "title": "Kickoff",
        "origin": "organizer_staff",
        "target_event_ids": [ctf_event.id],
        "audience_spec": {"kind": "event", "event_ids": [str(ctf_event.id)]},
        "trigger_spec": {"kind": "manual"},
        "channels": list(channels),
        "subject": "Welcome",
        "body": "Read the rules at [rules](/events/rules).",
    }
    data.update(overrides)
    return CampaignDraft(**data)


def _release(organizer_user, ctf_event, *, channels=("in_app", "email"), occurrence="occ-1"):
    campaign = create_campaign(organizer_user, _workspace_uuid(organizer_user), _draft(ctf_event, channels=channels))
    return release_campaign(campaign, occurrence_key=occurrence, actor_user_id=organizer_user.id)


# ---------------------------------------------------------------------------
# In-app availability is committed at admission, independent of the worker.
# ---------------------------------------------------------------------------


def test_release_commits_in_app_availability_without_a_worker(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    intent = _release(organizer_user, ctf_event, channels=["in_app"])

    # The durable inbox entry (receipt) exists at admission, before any worker runs.
    assert ParticipantReceipt.objects.filter(snapshot__intent=intent).count() == 1


def test_email_only_release_creates_no_in_app_receipt(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    intent = _release(organizer_user, ctf_event, channels=["email"])

    # Receipt existence must not expose an email-only item as an in-app inbox entry.
    assert ParticipantReceipt.objects.filter(snapshot__intent=intent).count() == 0
    assert DeliveryAttempt.objects.filter(intent=intent, channel="email").count() == 1


# ---------------------------------------------------------------------------
# Worker: in-app delivery outcomes.
# ---------------------------------------------------------------------------


def test_worker_accepts_account_less_in_app_delivery(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")  # no linked account -> nothing to wake
    _release(organizer_user, ctf_event, channels=["in_app"])

    stats = delivery_svc.run_once()

    assert stats.claimed == 1
    assert stats.accepted == 1
    attempt = DeliveryAttempt.objects.get(channel="in_app")
    assert attempt.status == DeliveryStatus.ACCEPTED.value
    assert attempt.result_reason == "no_socket_recipient"
    assert attempt.lease_token == ""
    assert attempt.observed_at is not None


def test_worker_publishes_wakeup_on_a_stable_identity(organizer_user, ctf_event, settings):
    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
    account = User.objects.create_user(username="p@test.com", email="p@test.com", password="x")  # nosec B106
    _participant(ctf_event, "p@test.com", user=account)
    _release(organizer_user, ctf_event, channels=["in_app"])

    stats = delivery_svc.run_once()

    assert stats.accepted == 1
    snapshot = RecipientSnapshot.objects.get()
    notifications = WebSocketNotification.objects.filter(recipient_id=account.id)
    # The wake-up uses the stable snapshot id as the replay identity, never the event UUID.
    assert notifications.count() == 1
    assert str(notifications.get().event_id) == str(snapshot.id)


def test_worker_does_not_claim_email_without_a_registered_adapter(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["email"])

    stats = delivery_svc.run_once()

    # Email has no adapter until #1525; the command is never claimed, downgraded, or accepted.
    assert stats.claimed == 0
    assert DeliveryAttempt.objects.get(channel="email").status == DeliveryStatus.QUEUED.value


def test_wakeup_replay_is_idempotent(organizer_user, ctf_event, settings):
    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
    account = User.objects.create_user(username="p@test.com", email="p@test.com", password="x")  # nosec B106
    _participant(ctf_event, "p@test.com", user=account)
    intent = _release(organizer_user, ctf_event, channels=["in_app"])
    snapshot = RecipientSnapshot.objects.get(intent=intent)
    refs = {"snapshot_id": str(snapshot.id), "intent_id": str(intent.id)}

    publish_communication_wakeup(
        event_id=ctf_event.id, recipient_user_id=account.id, snapshot_id=snapshot.id, references=refs
    )
    publish_communication_wakeup(
        event_id=ctf_event.id, recipient_user_id=account.id, snapshot_id=snapshot.id, references=refs
    )

    # A replayed wake-up maps to the same row: reconnect never duplicates the entry.
    assert WebSocketNotification.objects.filter(recipient_id=account.id).count() == 1


# ---------------------------------------------------------------------------
# Worker: fencing, staleness, retry/expiry, stale-lease recovery.
# ---------------------------------------------------------------------------


def test_worker_suppresses_delivery_when_intent_is_fenced_after_claim(organizer_user, ctf_event):
    from ctf.enums_communication import IntentStatus

    _participant(ctf_event, "a@test.com")
    intent = _release(organizer_user, ctf_event, channels=["in_app"])
    cfg = delivery_svc.WorkerConfig.from_settings()
    claimed = delivery_svc.claim_batch(cfg, now=timezone.now())
    assert len(claimed) == 1

    # A cancellation/fence lands after the claim; the worker suppresses before I/O.
    intent.status = IntentStatus.FENCED.value
    intent.save(update_fields=["status", "updated_at"])
    result = delivery_svc.process_attempt(claimed[0], cfg)

    assert result == DeliveryStatus.SUPPRESSED.value
    attempt = DeliveryAttempt.objects.get(pk=claimed[0].pk)
    assert attempt.status == DeliveryStatus.SUPPRESSED.value
    assert attempt.result_reason == "intent_fenced"


def test_worker_suppresses_when_participant_becomes_ineligible_after_claim(organizer_user, ctf_event):
    participant = _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["in_app"])
    cfg = delivery_svc.WorkerConfig.from_settings()
    claimed = delivery_svc.claim_batch(cfg, now=timezone.now())

    # The participant is banned (removed from viewing eligibility) after the claim.
    CTFParticipant.objects.filter(pk=participant.pk).update(status="banned")
    result = delivery_svc.process_attempt(claimed[0], cfg)

    assert result == DeliveryStatus.SUPPRESSED.value
    attempt = DeliveryAttempt.objects.get(pk=claimed[0].pk)
    assert attempt.status == DeliveryStatus.SUPPRESSED.value
    assert attempt.result_reason == "participant_ineligible"


def test_stale_worker_cannot_settle_a_reclaimed_command(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["in_app"])
    cfg = delivery_svc.WorkerConfig.from_settings()
    claimed = delivery_svc.claim_batch(cfg, now=timezone.now())
    stale = claimed[0]  # holds the old lease token in memory

    # Simulate another worker reclaiming the lease (new token).
    DeliveryAttempt.objects.filter(pk=stale.pk).update(lease_token="different-token")
    result = delivery_svc.process_attempt(stale, cfg)

    assert result == "stale"
    # The row keeps the reclaiming worker's lease, untouched by the stale worker.
    assert DeliveryAttempt.objects.get(pk=stale.pk).lease_token == "different-token"


def test_retriable_failure_expires_when_attempt_budget_is_exhausted(organizer_user, ctf_event, settings):
    # notifications disabled -> the in-app wake-up is "unavailable" -> retriable.
    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = False
    settings.CTF_COMMUNICATION_MAX_ATTEMPTS = 1
    account = User.objects.create_user(username="p@test.com", email="p@test.com", password="x")  # nosec B106
    _participant(ctf_event, "p@test.com", user=account)
    _release(organizer_user, ctf_event, channels=["in_app"])

    stats = delivery_svc.run_once()

    # attempt_number reaches the ceiling of 1 on the first try -> EXPIRED, not endless retry.
    assert stats.expired == 1
    assert DeliveryAttempt.objects.get(channel="in_app").status == DeliveryStatus.EXPIRED.value


def test_retriable_failure_schedules_a_backoff_retry(organizer_user, ctf_event, settings):
    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = False
    settings.CTF_COMMUNICATION_MAX_ATTEMPTS = 5
    account = User.objects.create_user(username="p@test.com", email="p@test.com", password="x")  # nosec B106
    _participant(ctf_event, "p@test.com", user=account)
    _release(organizer_user, ctf_event, channels=["in_app"])

    delivery_svc.run_once()

    attempt = DeliveryAttempt.objects.get(channel="in_app")
    assert attempt.status == DeliveryStatus.RETRY_DUE.value
    assert attempt.due_at > timezone.now()
    assert attempt.lease_token == ""


def test_claim_recovers_a_stale_lease(organizer_user, ctf_event):
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["in_app"])
    attempt = DeliveryAttempt.objects.get(channel="in_app")
    # Simulate a crashed worker: CLAIMED with an expired lease and an old token.
    DeliveryAttempt.objects.filter(pk=attempt.pk).update(
        status=DeliveryStatus.CLAIMED.value,
        lease_token="dead-worker",
        lease_expires_at=timezone.now() - timedelta(minutes=5),
        attempt_number=1,
    )

    cfg = delivery_svc.WorkerConfig.from_settings()
    claimed = delivery_svc.claim_batch(cfg, now=timezone.now())

    assert len(claimed) == 1
    reclaimed = DeliveryAttempt.objects.get(pk=attempt.pk)
    assert reclaimed.lease_token not in ("", "dead-worker")  # a fresh lease fences the dead worker
    assert reclaimed.attempt_number == 2  # crash/reclaim consumes the attempt budget too


# ---------------------------------------------------------------------------
# Channel adapter outcomes: a registered adapter's terminal/suppressed result.
# ---------------------------------------------------------------------------


@pytest.fixture
def registered_email_adapter():
    """Register a controllable fake adapter for the email channel; restore after.

    Email has no real adapter until #1525, so registering one here lets the worker
    claim email commands and exercise the terminal/suppressed settle paths.
    """
    box = {"outcome": DeliveryOutcome(OutcomeClass.TERMINAL, reason="hard_bounce")}

    class _FakeEmailAdapter:
        channel = "email"

        def deliver(self, command, *, timeout):
            return box["outcome"]

    register_adapter(_FakeEmailAdapter())
    try:
        yield box
    finally:
        adapter_contract._ADAPTERS.pop("email", None)


def test_worker_records_a_terminal_channel_failure(organizer_user, ctf_event, registered_email_adapter):
    registered_email_adapter["outcome"] = DeliveryOutcome(OutcomeClass.TERMINAL, reason="hard_bounce")
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["email"])

    stats = delivery_svc.run_once()

    assert stats.failed == 1
    attempt = DeliveryAttempt.objects.get(channel="email")
    assert attempt.status == DeliveryStatus.PERMANENT_FAILURE.value
    assert attempt.result_reason == "hard_bounce"


def test_worker_records_an_adapter_suppression(organizer_user, ctf_event, registered_email_adapter):
    registered_email_adapter["outcome"] = DeliveryOutcome(OutcomeClass.SUPPRESSED, reason="opted_out")
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["email"])

    stats = delivery_svc.run_once()

    assert stats.suppressed == 1
    assert DeliveryAttempt.objects.get(channel="email").status == DeliveryStatus.SUPPRESSED.value


def test_worker_retries_when_the_adapter_raises(organizer_user, ctf_event, registered_email_adapter, settings):
    settings.CTF_COMMUNICATION_MAX_ATTEMPTS = 5

    class _Boom:
        channel = "email"

        def deliver(self, command, *, timeout):
            raise RuntimeError("provider exploded")

    register_adapter(_Boom())
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["email"])

    stats = delivery_svc.run_once()

    # A raising adapter is caught and treated as retriable, never aborting the batch.
    assert stats.retried == 1
    assert DeliveryAttempt.objects.get(channel="email").status == DeliveryStatus.RETRY_DUE.value


def test_drain_command_processes_one_batch(organizer_user, ctf_event, capsys):
    _participant(ctf_event, "a@test.com")
    _release(organizer_user, ctf_event, channels=["in_app"])

    call_command("drain_ctf_communication_deliveries")

    assert DeliveryAttempt.objects.get(channel="in_app").status == DeliveryStatus.ACCEPTED.value
    assert "claimed=1" in capsys.readouterr().out
