"""Scheduled communication declarations and due-time release (#2099, CTF-010).

A scheduled communication is a *future declaration*, not a released delivery.
``schedule_declaration`` commits an immutable SCHEDULED ``CommunicationIntent``
(the authored occurrence, carrying ``due_at`` and source/generation evidence) and
its ``CTFScheduledTask`` (the mutable execution index) in one transaction, so a
crash between scheduling and release loses neither. The audience is resolved and
materialized only at the eligible occurrence, by ``release_due_declaration``
(``ctf.services.communication.release``), which re-enters the one admission
transaction and its lateness/expiry policy.

Repeated ticks, run-now, restart, and stale recovery all re-enter that same
admission/fence path, so they collapse onto the one authorized occurrence or
reject on conflicting meaning — never a second delivery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
from ctf.enums_communication import CampaignStatus, IntentStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationCampaign, CommunicationIntent, CTFEvent, CTFScheduledTask, MessageRevision
from ctf.services.communication.admission import (
    AdmissionActor,
    assert_occurrence_ready,
    assert_source_realizable,
    reauthorize,
)
from ctf.services.communication.backpressure import RETRYABLE_ADMISSION_CODES
from ctf.services.communication.release import (
    RELEASE_OUTCOME_NOT_DUE,
    _assert_release_allowed,
    _assert_replay_matches,
    _idempotency_key,
    _resolve_revision,
    release_due_declaration,
)

logger = logging.getLogger(__name__)

# How soon a due-time release retries after transient backpressure. The grace
# window (via release_due_declaration) bounds total lateness, so this only paces
# retries; it does not by itself decide expiry.
_BACKPRESSURE_RETRY_SECONDS = 60


def _actor_for_scheduled(intent: CommunicationIntent) -> AdmissionActor:
    """Reconstruct the admitting actor recorded on a scheduled declaration.

    The stored non-secret actor/token identity drives the due-time re-check: a
    human declaration revalidates that user's live authority, a token declaration
    stays fail-closed, and a declaration authored by trusted automation (no user,
    no token) re-enters as system authority.
    """
    if intent.actor_token_id is not None:
        return AdmissionActor(token_id=intent.actor_token_id)
    if intent.actor_user_id is not None:
        return AdmissionActor(user_id=intent.actor_user_id)
    return AdmissionActor(system=True)


def schedule_declaration(
    campaign: CommunicationCampaign,
    *,
    due_at: datetime,
    occurrence_key: str,
    actor: AdmissionActor,
    revision: MessageRevision | None = None,
    range_generation_ref: str = "",
) -> CommunicationIntent:
    """Commit a future communication declaration and its release task together.

    Re-checks authority now (schedule time) and records the declaration so the
    due-time path can re-check it again. Idempotent: re-scheduling the same
    campaign/occurrence/generation returns the existing declaration rather than
    creating a second one or a second task.
    """
    assert_source_realizable(campaign.trigger_spec["kind"])
    # raw caller request, before default-latest resolution
    requested_revision = revision
    key = _idempotency_key(campaign.id, occurrence_key, range_generation_ref)
    now = timezone.now()
    target_event_ids = list(campaign.target_events.values_list("id", flat=True))

    with transaction.atomic():
        target_events = list(CTFEvent.objects.select_for_update().filter(id__in=target_event_ids).order_by("pk"))
        reauthorize(campaign, target_events, actor)
        locked_campaign = CommunicationCampaign.objects.select_for_update().get(pk=campaign.pk)

        existing = CommunicationIntent.objects.filter(idempotency_key=key).first()
        if existing is not None:
            if existing.campaign_id != locked_campaign.pk:
                raise CTFCommunicationError(
                    "Idempotency identity does not match this campaign",
                    code="CTF_COMMUNICATION_IDEMPOTENCY_MISMATCH",
                )
            # Re-scheduling the same occurrence with a different authored meaning
            # (revision, due time, or actor) is a conflict, not a silent no-op.
            _assert_replay_matches(
                existing, requested_revision=requested_revision, requested_due_at=due_at, actor=actor
            )
            return existing

        if not target_events:
            raise CTFCommunicationError(
                "A scheduled campaign must target at least one event", code="CTF_COMMUNICATION_NO_TARGETS"
            )
        # Occurrence gate: the schedule's due time must reconcile with the campaign's
        # absolute-time trigger, and a lifecycle source is not clock-schedulable.
        assert_occurrence_ready(locked_campaign, target_events, now=now, immediate=False, due_at=due_at)
        _assert_release_allowed(locked_campaign, target_events)
        revision = _resolve_revision(locked_campaign, revision)

        intent = CommunicationIntent.objects.create(
            campaign=locked_campaign,
            revision=revision,
            status=IntentStatus.SCHEDULED.value,
            trigger_kind=locked_campaign.trigger_spec["kind"],
            origin=locked_campaign.origin,
            actor_user_id=actor.user_id,
            actor_token_id=actor.token_id,
            channels=list(locked_campaign.channels),
            acknowledgement_policy=locked_campaign.acknowledgement_policy,
            occurrence_key=occurrence_key,
            idempotency_key=key,
            range_generation_ref=range_generation_ref,
            due_at=due_at,
        )
        CommunicationCampaign.objects.filter(pk=locked_campaign.pk).update(
            status=CampaignStatus.SCHEDULED.value, updated_at=now
        )
        # The task's event is only a routing anchor; the intent carries the full
        # authorization/audience scope. ``scheduled_for`` starts at the authored due
        # time and is the mutable execution index only (retry/resume overwrite it).
        CTFScheduledTask.objects.create(
            event=target_events[0],
            task_type=ScheduledTaskType.RELEASE_COMMUNICATION.value,
            scheduled_for=due_at,
            status=ScheduledTaskStatus.PENDING.value,
            metadata={"intent_id": str(intent.id)},
        )
    logger.info("Scheduled communication intent %s for campaign %s due %s", intent.id, campaign.id, due_at)
    return intent


def run_release_communication_task(task: CTFScheduledTask) -> dict[str, Any]:
    """Scheduler handler for a RELEASE_COMMUNICATION task.

    Reloads the authoritative declaration by its typed id (never trusting free-form
    task metadata as privilege), then re-enters the admission/lateness path. Returns
    a scheduler result dict: ``{"reschedule_for": due_at}`` when the occurrence is
    not yet due (early tick / backward clock jump), otherwise a normal completion
    result. A denial at due time (revoked/unauthorized/token) admits no work and is
    terminal, not a retry storm.
    """
    intent_id = (task.metadata or {}).get("intent_id")
    if not intent_id:
        raise ValueError(f"RELEASE_COMMUNICATION task {task.pk} has no intent_id")
    intent = CommunicationIntent.objects.filter(pk=intent_id).first()
    if intent is None:
        logger.warning("RELEASE_COMMUNICATION task %s references missing intent %s", task.pk, intent_id)
        return {"outcome": "missing_intent"}

    actor = _actor_for_scheduled(intent)
    try:
        outcome = release_due_declaration(intent, actor=actor)
    except CTFCommunicationError as exc:
        return _denied_result(intent, exc)

    result: dict[str, Any] = {"outcome": outcome}
    if outcome == RELEASE_OUTCOME_NOT_DUE and intent.due_at is not None:
        result["reschedule_for"] = intent.due_at
    return result


def _denied_result(intent: CommunicationIntent, exc: CTFCommunicationError) -> dict[str, Any]:
    """Map an admission denial at due time to a scheduler result.

    Transient backpressure reschedules a bounded retry (the grace window still caps
    total lateness); a permanent denial records a terminal no-work outcome instead
    of leaving the intent SCHEDULED with a completed task.
    """
    if exc.code in RETRYABLE_ADMISSION_CODES:
        logger.info("Scheduled communication %s hit transient backpressure (%s); retrying", intent.id, exc.code)
        return {
            "reschedule_for": timezone.now() + timedelta(seconds=_BACKPRESSURE_RETRY_SECONDS),
            "outcome": "backpressure_retry",
        }
    _expire_unadmittable(intent, exc.code)
    return {"outcome": "denied"}


def _expire_unadmittable(intent: CommunicationIntent, code: str) -> None:
    """Mark a scheduled intent EXPIRED when a permanent denial makes it un-admittable."""
    updated = CommunicationIntent.objects.filter(pk=intent.pk, status=IntentStatus.SCHEDULED.value).update(
        status=IntentStatus.EXPIRED.value, updated_at=timezone.now()
    )
    if updated:
        logger.info("Scheduled communication %s reached a terminal no-work outcome at due time (%s)", intent.id, code)


def request_early_release(intent: CommunicationIntent, *, actor: AdmissionActor) -> str:
    """Authorized organizer run-now: release a scheduled declaration before due time.

    Early release is offered only to a live session actor carrying an explicit
    early-release grant; token/system early release is not available here. The full
    admission re-check (workspace mutex + per-event notification authority) still
    runs inside ``release_due_declaration``.
    """
    if actor.user_id is None or not actor.allow_early_release:
        raise CTFCommunicationError(
            "Early release of a scheduled communication is not authorized",
            code="CTF_COMMUNICATION_EARLY_RELEASE_DENIED",
        )
    return release_due_declaration(intent, actor=actor, allow_early=True)
