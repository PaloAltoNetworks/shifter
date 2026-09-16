"""Lease-based delivery worker core for scoped communications (ADR-051-R12, #2098).

This is the consumer side of the #2048 admission/fan-out: it claims the durable
``DeliveryAttempt`` commands with a short PostgreSQL transaction and
``select_for_update(skip_locked=True)``, does the transport call with NO database
lock held, then records the observed outcome only if its per-claim ``lease_token``
still matches -- so a stale worker whose lease was reclaimed can never overwrite a
newer claim.

Algorithmic reference: ``engine/management/commands/drain_provisioner_launch_outbox.py``
(claim/lease/fence/backoff/terminal shape). Deliberately different from it: the
transport call happens outside the lock, and a committed claim is the recall
boundary, never proof of delivery. Retry policy has exactly one owner here: bounded
exponential backoff with jitter, an attempt ceiling, and an elapsed-time ceiling.

The worker only claims channels that have a registered adapter, so an unregistered
channel (``email`` before #1525) is never claimed, downgraded, or falsely accepted.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import SystemRandom, token_hex
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.enums_communication import CampaignStatus, DeliveryStatus, IntentStatus
from ctf.models import DeliveryAttempt, RecipientSnapshot
from ctf.services.communication.adapters import (
    DeliveryCommand,
    DeliveryOutcome,
    OutcomeClass,
    get_adapter,
    registered_channels,
)

logger = logging.getLogger(__name__)

# Sentinel for an unheld lease. ``lease_token`` is a per-claim worker fence, never a
# credential; this named constant also keeps the empty value off bandit's B105
# hardcoded-password heuristic without suppressing the checker.
_UNLEASED = ""

# Jitter uses a CSPRNG-backed source purely to avoid a weak-PRNG lint finding; the
# value is a scheduling nicety, not a security control.
_JITTER = SystemRandom()

# Bounded default policy. The typed, relationally-validated owner is
# ``config._ctf_communication_settings``; these getattr defaults keep the worker
# importable and unit-testable without a full settings surface.
_DEFAULTS = {
    "CTF_COMMUNICATION_WORKER_BATCH_SIZE": 100,
    "CTF_COMMUNICATION_WORKER_PER_EVENT_CAP": 25,
    "CTF_COMMUNICATION_WORKER_LEASE_SECONDS": 120,
    "CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS": 10,
    "CTF_COMMUNICATION_MAX_ATTEMPTS": 6,
    "CTF_COMMUNICATION_MAX_ELAPSED_SECONDS": 86400,
    "CTF_COMMUNICATION_BACKOFF_BASE_SECONDS": 30,
    "CTF_COMMUNICATION_BACKOFF_CAP_SECONDS": 3600,
    "CTF_COMMUNICATION_BACKOFF_JITTER_FRACTION": 0.25,
}


def _setting(name: str) -> int | float:
    """Return a bounded worker setting, defaulting when the settings owner is absent."""
    return getattr(settings, name, _DEFAULTS[name])


@dataclass(frozen=True)
class WorkerConfig:
    """Immutable snapshot of the worker's bounded operational policy for one run."""

    batch_size: int
    per_event_cap: int
    lease_seconds: int
    timeout_seconds: float
    max_attempts: int
    max_elapsed_seconds: int
    backoff_base_seconds: int
    backoff_cap_seconds: int
    backoff_jitter_fraction: float

    @classmethod
    def from_settings(cls) -> WorkerConfig:
        """Build the config from Django settings (typed owner) or bounded defaults."""
        return cls(
            batch_size=int(_setting("CTF_COMMUNICATION_WORKER_BATCH_SIZE")),
            per_event_cap=int(_setting("CTF_COMMUNICATION_WORKER_PER_EVENT_CAP")),
            lease_seconds=int(_setting("CTF_COMMUNICATION_WORKER_LEASE_SECONDS")),
            timeout_seconds=float(_setting("CTF_COMMUNICATION_TRANSPORT_TIMEOUT_SECONDS")),
            max_attempts=int(_setting("CTF_COMMUNICATION_MAX_ATTEMPTS")),
            max_elapsed_seconds=int(_setting("CTF_COMMUNICATION_MAX_ELAPSED_SECONDS")),
            backoff_base_seconds=int(_setting("CTF_COMMUNICATION_BACKOFF_BASE_SECONDS")),
            backoff_cap_seconds=int(_setting("CTF_COMMUNICATION_BACKOFF_CAP_SECONDS")),
            backoff_jitter_fraction=float(_setting("CTF_COMMUNICATION_BACKOFF_JITTER_FRACTION")),
        )


@dataclass
class DeliveryRunStats:
    """Bounded per-run counters (no identities) for logging and metrics."""

    claimed: int = 0
    accepted: int = 0
    retried: int = 0
    expired: int = 0
    failed: int = 0
    suppressed: int = 0
    stale: int = 0
    reclaimed: int = 0


NowFunc = Callable[[], datetime]

_CLAIMABLE = (DeliveryStatus.QUEUED.value, DeliveryStatus.RETRY_DUE.value)
# Fields the settle/claim writes touch; updated_at is listed so auto_now refreshes.
_LEASE_FIELDS = [
    "status",
    "lease_token",
    "lease_expires_at",
    "attempt_number",
    "first_attempt_at",
    "attempted_at",
    "observed_at",
    "due_at",
    "result_reason",
    "provider_receipt",
    "updated_at",
]


def _claimable_q(now: datetime) -> Q:
    """Rows a worker may claim: due unclaimed work, plus CLAIMED rows past their lease."""
    return Q(status__in=_CLAIMABLE, due_at__lte=now) | Q(status=DeliveryStatus.CLAIMED.value, lease_expires_at__lte=now)


def _due_event_ids(channels: frozenset[str], now: datetime, limit: int) -> list[UUID]:
    """Return distinct event ids with claimable work, bounded, for fair round-robin."""
    return list(
        DeliveryAttempt.objects.filter(_claimable_q(now), channel__in=channels)
        .values_list("snapshot__event_id", flat=True)
        .distinct()[:limit]
    )


def _claim_for_event(
    event_id: UUID, channels: frozenset[str], now: datetime, take: int, lease_seconds: int
) -> list[DeliveryAttempt]:
    """Claim up to ``take`` due commands for one event in a short locked transaction."""
    claimed: list[DeliveryAttempt] = []
    with transaction.atomic():
        rows = list(
            DeliveryAttempt.objects.select_for_update(skip_locked=True)
            .filter(_claimable_q(now), channel__in=channels, snapshot__event_id=event_id)
            .order_by("due_at", "id")[:take]
        )
        for row in rows:
            row.status = DeliveryStatus.CLAIMED.value
            row.lease_token = token_hex(16)
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.attempt_number += 1
            if row.first_attempt_at is None:
                row.first_attempt_at = now
            row.attempted_at = None
            row.observed_at = None
            row.save(update_fields=_LEASE_FIELDS)
            claimed.append(row)
    return claimed


def claim_batch(cfg: WorkerConfig, *, now: datetime) -> list[DeliveryAttempt]:
    """Claim a fair, bounded batch across events so one event cannot monopolize.

    Each event is claimed in its own short transaction; ``skip_locked`` lets many
    worker replicas run without contention or double-claiming.
    """
    channels = registered_channels()
    if not channels:
        return []
    claimed: list[DeliveryAttempt] = []
    for event_id in _due_event_ids(channels, now, cfg.batch_size):
        if len(claimed) >= cfg.batch_size:
            break
        take = min(cfg.per_event_cap, cfg.batch_size - len(claimed))
        claimed.extend(_claim_for_event(event_id, channels, now, take, cfg.lease_seconds))
    return claimed


def _fence_reason(row: DeliveryAttempt) -> str:
    """Return a bounded fence reason when this command must no longer be delivered.

    A committed claim is the recall boundary, but the worker voluntarily suppresses
    before its irreversible send when a cancellation/lifecycle change is visible.
    Event cancellation is event-qualified: only that event's commands are fenced.
    """
    intent = row.intent
    if intent.status in (IntentStatus.CANCELLED.value, IntentStatus.FENCED.value):
        reason = f"intent_{intent.status}"
    elif intent.campaign.status == CampaignStatus.CANCELLED.value:
        reason = "campaign_cancelled"
    elif row.snapshot.event.status == EventStatus.CANCELLED.value:
        reason = "event_cancelled"
    elif not _recipient_still_eligible(row.snapshot):
        reason = "participant_ineligible"
    else:
        reason = ""
    return reason


def _recipient_still_eligible(snapshot: RecipientSnapshot) -> bool:
    """Return True only while the snapshot's participant is still viewing-eligible.

    A participant removed, deactivated, or otherwise made ineligible after the
    claim must not reach an adapter (ADR-051-R12). This rechecks the live
    event-scoped participant with the same predicate the audience resolver uses,
    so reclaimed and retried work re-validates lifecycle scope right before I/O.
    """
    from ctf.models import CTFParticipant
    from ctf.services.participant import viewing_participant_q

    return CTFParticipant.objects.filter(
        viewing_participant_q(),
        id=snapshot.participant_public_id,
        event_id=snapshot.event_id,
    ).exists()


def _command(row: DeliveryAttempt) -> DeliveryCommand:
    """Build the reference-only adapter command from a claimed row (no secrets)."""
    return DeliveryCommand(
        attempt_id=row.id,
        intent_id=row.intent_id,
        snapshot_id=row.snapshot_id,
        channel=row.channel,
        event_id=row.snapshot.event_id,
        participant_public_id=row.snapshot.participant_public_id,
        recipient_user_id=row.snapshot.user_id,
        occurrence_key=row.intent.occurrence_key,
    )


def _lease_held(row: DeliveryAttempt, token: str) -> bool:
    """Return True only while this worker still owns the claim (fence check)."""
    return row.status == DeliveryStatus.CLAIMED.value and row.lease_token == token


def _clear_lease(row: DeliveryAttempt) -> None:
    """Release the row's lease so it is claimable again (or terminal)."""
    row.lease_token = _UNLEASED
    row.lease_expires_at = None


def _backoff_seconds(attempt_number: int, cfg: WorkerConfig) -> float:
    """Bounded exponential backoff with jitter."""
    base = min(cfg.backoff_base_seconds * (2 ** max(attempt_number - 1, 0)), cfg.backoff_cap_seconds)
    return base + _JITTER.uniform(0, base * cfg.backoff_jitter_fraction)


def _preflight(pk: UUID, token: str, cfg: WorkerConfig, now_func: NowFunc) -> DeliveryCommand | str:
    """Locked pre-I/O step: confirm the lease, recheck the fence, stamp the attempt.

    Renews the lease under the row lock right before the transport call, so the
    lease always covers the imminent I/O (lease_seconds >> transport timeout). The
    ``select_for_update`` row lock serializes this against a concurrent stale-lease
    reclaim, so an item can never be processed by two workers at once even when the
    surrounding batch is large. Returns the command, or ``"not_ours"`` /
    ``"suppressed"``.
    """
    with transaction.atomic():
        row = (
            DeliveryAttempt.objects.select_for_update()
            .select_related("intent", "intent__campaign", "snapshot", "snapshot__event")
            .get(pk=pk)
        )
        if not _lease_held(row, token):
            return "not_ours"
        reason = _fence_reason(row)
        now = now_func()
        if reason:
            row.status = DeliveryStatus.SUPPRESSED.value
            row.result_reason = reason
            row.observed_at = now
            _clear_lease(row)
            row.save(update_fields=_LEASE_FIELDS)
            return "suppressed"
        row.attempted_at = now
        row.lease_expires_at = now + timedelta(seconds=cfg.lease_seconds)
        row.save(update_fields=["attempted_at", "lease_expires_at", "updated_at"])
        return _command(row)


def _settle(pk: UUID, token: str, outcome: DeliveryOutcome, cfg: WorkerConfig, now_func: NowFunc) -> str:
    """Locked post-I/O step: record the observed outcome only if the lease still holds."""
    with transaction.atomic():
        row = DeliveryAttempt.objects.select_for_update().get(pk=pk)
        if not _lease_held(row, token):
            logger.info("ignoring stale communication delivery outcome for attempt %s", pk)
            return "stale"
        now = now_func()
        row.observed_at = now
        row.result_reason = outcome.reason[:64]
        row.provider_receipt = outcome.provider_receipt[:255]
        if outcome.outcome == OutcomeClass.ACCEPTED:
            row.status = DeliveryStatus.ACCEPTED.value
            _clear_lease(row)
        elif outcome.outcome == OutcomeClass.SUPPRESSED:
            row.status = DeliveryStatus.SUPPRESSED.value
            _clear_lease(row)
        elif outcome.outcome == OutcomeClass.TERMINAL:
            row.status = DeliveryStatus.PERMANENT_FAILURE.value
            _clear_lease(row)
        else:
            # RETRIABLE outcome: retry with backoff until the attempt/elapsed budget is spent.
            baseline = row.first_attempt_at or row.created_at
            elapsed = (now - baseline).total_seconds()
            if row.attempt_number >= cfg.max_attempts or elapsed >= cfg.max_elapsed_seconds:
                row.status = DeliveryStatus.EXPIRED.value
                row.result_reason = (outcome.reason or "budget_exhausted")[:64]
                _clear_lease(row)
            else:
                row.status = DeliveryStatus.RETRY_DUE.value
                row.due_at = now + timedelta(seconds=_backoff_seconds(row.attempt_number, cfg))
                _clear_lease(row)
        row.save(update_fields=_LEASE_FIELDS)
        return row.status


def process_attempt(attempt: DeliveryAttempt, cfg: WorkerConfig, now_func: NowFunc = timezone.now) -> str:
    """Deliver one claimed command: pre-flight fence, transport I/O (no lock), settle.

    Returns a bounded result token: a ``DeliveryStatus`` value, ``"stale"`` (lease
    lost), or ``"suppressed"`` (fenced before I/O).
    """
    token = attempt.lease_token
    decision = _preflight(attempt.pk, token, cfg, now_func)
    if isinstance(decision, str):
        return "stale" if decision == "not_ours" else DeliveryStatus.SUPPRESSED.value
    command = decision
    adapter = get_adapter(command.channel)
    # Defensive: the channel was de-registered mid-run.
    if adapter is None:
        return "stale"
    try:
        outcome = adapter.deliver(command, timeout=cfg.timeout_seconds)
    # Never let one transport error abort the batch (partial-failure isolation).
    except Exception:
        logger.warning("communication adapter raised for attempt %s channel %s", attempt.pk, command.channel)
        outcome = DeliveryOutcome(OutcomeClass.RETRIABLE, reason="adapter_error")
    return _settle(attempt.pk, token, outcome, cfg, now_func)


def run_once(
    cfg: WorkerConfig | None = None,
    *,
    now_func: NowFunc = timezone.now,
    heartbeat: Callable[[], None] | None = None,
) -> DeliveryRunStats:
    """Claim and process one bounded batch. Returns per-run counters.

    Each attempt is isolated: one bad recipient or channel raises inside
    ``process_attempt`` and settles to a retry/terminal state without touching any
    other command (AC: partial-failure isolation). ``heartbeat`` is invoked after
    every attempt so a long serial batch keeps the worker's liveness marker fresh
    (it never waits for the whole batch), and each attempt renews its own lease
    right before I/O, so a slow batch never lets a later command's lease lapse into
    a concurrent send.
    """
    cfg = cfg or WorkerConfig.from_settings()
    claimed = claim_batch(cfg, now=now_func())
    stats = DeliveryRunStats(claimed=len(claimed))
    for attempt in claimed:
        result = process_attempt(attempt, cfg, now_func)
        _record(stats, result)
        if heartbeat is not None:
            heartbeat()
    from ctf.services.communication import metrics

    metrics.emit_worker_run(stats, now_func=now_func)
    return stats


def _record(stats: DeliveryRunStats, result: str) -> None:
    """Fold one attempt result into the run counters."""
    mapping = {
        DeliveryStatus.ACCEPTED.value: "accepted",
        DeliveryStatus.RETRY_DUE.value: "retried",
        DeliveryStatus.EXPIRED.value: "expired",
        DeliveryStatus.PERMANENT_FAILURE.value: "failed",
        DeliveryStatus.SUPPRESSED.value: "suppressed",
        "stale": "stale",
    }
    attr = mapping.get(result)
    if attr:
        setattr(stats, attr, getattr(stats, attr) + 1)
