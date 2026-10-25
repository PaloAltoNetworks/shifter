"""Intent release for scoped communications (ADR-051, #2048).

Releasing a campaign resolves the audience server-side and, in ONE locked
transaction, writes the immutable intent, the deterministic per-recipient
snapshots and in-app receipts, the initial per-channel delivery commands, and a
strict audit event. PostgreSQL is authoritative; nothing calls a transport
before commit.

Release is linearized against cancellation and fencing: it takes the campaign and
target-event row locks, re-checks the campaign/event fences and resolves
recipients INSIDE the transaction, and its idempotency identity is scoped to the
immutable campaign so a replay can never return another campaign's intent. A
retry collapses onto the same intent, and per-recipient uniqueness means it can
never grow the audience (AC2, AC3).

The RAES/range-source reference columns on ``CommunicationIntent`` are populated
by the later RAES/range-ingress slices; this slice releases manual and
event-scoped campaigns and carries only the range-generation fence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ctf.communication_contracts import canonical_digest
from ctf.enums import EventStatus
from ctf.enums_communication import CampaignStatus, CommunicationChannel, DeliveryStatus, IntentStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import (
    CommunicationCampaign,
    CommunicationIntent,
    CTFEvent,
    CTFParticipant,
    DeliveryAttempt,
    MessageRevision,
    ParticipantReceipt,
    RecipientSnapshot,
)
from ctf.services.audit import audit_communication_release
from ctf.services.communication.admission import (
    AdmissionActor,
    assert_occurrence_ready,
    assert_source_realizable,
    reauthorize,
)
from ctf.services.communication.audience import resolve_recipients
from ctf.services.communication.backpressure import AdmissionRequest, enforce_admission

logger = logging.getLogger(__name__)


def _legacy_workspace_id(campaign: CommunicationCampaign) -> int:
    """Reject campaign scopes unsupported by the workspace release service."""
    if campaign.workspace_id is None:
        raise CTFCommunicationError(
            "Campaign is not available for workspace communications",
            code="CTF_COMMUNICATION_WORKSPACE_DENIED",
        )
    return campaign.workspace_id


def _idempotency_key(campaign_id: UUID, occurrence_key: str, range_generation_ref: str) -> str:
    """Derive a campaign-scoped, unambiguous intent identity.

    The digest namespaces the caller-supplied occurrence and bound range
    generation with the immutable campaign id, using a structured (not
    delimiter-joined) encoding so different component tuples cannot collide onto
    one key or onto another campaign's intent.
    """
    return canonical_digest(
        {
            "campaign": str(campaign_id),
            "occurrence": occurrence_key,
            "generation": range_generation_ref,
        }
    )


def _assert_replay_matches(
    existing: CommunicationIntent,
    *,
    requested_revision: MessageRevision | None,
    requested_due_at: datetime | None,
    actor: AdmissionActor,
) -> None:
    """Reject a same-key replay that requests a different immutable declaration.

    Occurrence identity (campaign + occurrence + range generation) is not enough:
    an idempotent retry must return the *same* authorized declaration, so a replay
    that explicitly requests a different revision, due time, or actor identity is a
    conflict, not a silent no-op (#2099, AC1). Only explicitly-supplied values are
    compared — a bare retry that supplies neither revision nor due time collapses
    onto the existing occurrence as before.
    """
    conflicts: list[str] = []
    if requested_revision is not None and existing.revision_id != requested_revision.pk:
        conflicts.append("revision")
    if requested_due_at is not None and existing.due_at != requested_due_at:
        conflicts.append("due_at")
    if actor.user_id is not None and existing.actor_user_id != actor.user_id:
        conflicts.append("actor")
    if actor.token_id is not None and existing.actor_token_id != actor.token_id:
        conflicts.append("actor_token")
    if conflicts:
        raise CTFCommunicationError(
            f"Replay conflicts with the released declaration ({', '.join(conflicts)})",
            code="CTF_COMMUNICATION_DECLARATION_CONFLICT",
        )


def _assert_release_allowed(campaign: CommunicationCampaign, target_events: list[CTFEvent]) -> None:
    """Refuse release for a cancelled campaign or a cancelled target event.

    ``target_events`` are the live target-event rows already locked by the caller
    in primary-key order (the canonical order shared with lifecycle operations),
    so a concurrent event cancellation cannot slip between this status check and
    the materialization below. Checking status on the locked rows — rather than a
    fresh query filtered to ``CANCELLED`` — is what makes the lock cover every live
    target, not only the already-cancelled ones.
    """
    from ctf.models import CommunicationCutover, LegacyCommunication
    from ctf.services.communication.adapters import registered_channels

    if LegacyCommunication.objects.filter(campaign=campaign).exists():
        if not CommunicationCutover.objects.filter(pk=1, activated_at__isnull=False).exists():
            raise CTFCommunicationError("Cutover not active", code="CTF_COMMUNICATION_CUTOVER_BLOCKED")
        if set(campaign.channels) - set(registered_channels()):
            raise CTFCommunicationError("Channel unavailable", code="CTF_COMMUNICATION_CHANNEL_UNAVAILABLE")
    if campaign.status == CampaignStatus.CANCELLED.value:
        raise CTFCommunicationError("A cancelled campaign cannot be released", code="CTF_COMMUNICATION_CANCELLED")
    if any(event.status == EventStatus.CANCELLED.value for event in target_events):
        raise CTFCommunicationError(
            "A target event is cancelled; the campaign must be replaced",
            code="CTF_COMMUNICATION_EVENT_CANCELLED",
        )


def _resolve_revision(campaign: CommunicationCampaign, revision: MessageRevision | None) -> MessageRevision:
    """Return the revision to release, defaulting to the latest and validating ownership."""
    revision = revision or MessageRevision.objects.filter(campaign=campaign).order_by("-revision_number").first()
    if revision is None:
        raise CTFCommunicationError("Campaign has no message revision to release", code="CTF_COMMUNICATION_NO_CONTENT")
    if revision.campaign_id != campaign.pk:
        raise CTFCommunicationError(
            "Message revision does not belong to this campaign",
            code="CTF_COMMUNICATION_REVISION_MISMATCH",
        )
    return revision


def _materialize(
    intent: CommunicationIntent, recipients: list[CTFParticipant], channels: list[str], now: datetime
) -> None:
    """Write the per-recipient snapshots, receipts, and per-channel delivery commands.

    In-app availability is committed here, at admission: when ``in_app`` is a
    selected channel the ``ParticipantReceipt`` (the durable inbox entry) is created
    in this transaction, so availability never depends on a worker later processing
    the queued wake-up command (#2098). When ``in_app`` is not selected no receipt is
    created, so an email-only campaign never exposes an in-app inbox item.
    """
    in_app_selected = CommunicationChannel.IN_APP.value in channels
    for participant in recipients:
        snapshot = RecipientSnapshot.objects.create(
            intent=intent,
            event_id=participant.event_id,
            participant=participant,
            participant_public_id=participant.id,
            team_id=participant.team_id,
            user_id=participant.user_id,
            delivery_coordinate=participant.email or "",
        )
        if in_app_selected:
            ParticipantReceipt.objects.create(snapshot=snapshot)
        DeliveryAttempt.objects.bulk_create(
            [
                DeliveryAttempt(
                    intent=intent,
                    snapshot=snapshot,
                    channel=channel,
                    status=DeliveryStatus.QUEUED.value,
                    idempotency_key=f"{intent.idempotency_key}:{participant.id}:{channel}",
                    due_at=intent.due_at or now,
                )
                for channel in channels
            ]
        )


def release_campaign(
    campaign: CommunicationCampaign,
    *,
    occurrence_key: str,
    actor_user_id: int | None = None,
    actor_token_id: int | None = None,
    revision: MessageRevision | None = None,
    range_generation_ref: str = "",
    admission: AdmissionActor | None = None,
) -> CommunicationIntent:
    """Release ``campaign`` as one immutable intent with materialized recipients.

    This is the one admission transaction (ADR-051-R12): it locks the live target
    events in primary-key order (the canonical order shared with lifecycle), then
    re-derives and re-checks authority for the admitting ``admission`` actor before
    doing any work, then commits the intent, snapshots, receipts, delivery
    commands, and audit together. The legacy ``actor_user_id`` / ``actor_token_id``
    keywords build a live-session / token ``AdmissionActor`` when ``admission`` is
    not supplied.

    Returns the released intent. A second call with the same campaign, occurrence,
    and range generation returns the existing intent unchanged (at-least-once
    replay collapse), so the audience never grows on retry.
    """
    actor = admission if admission is not None else AdmissionActor(user_id=actor_user_id, token_id=actor_token_id)
    assert_source_realizable(campaign.trigger_spec["kind"])
    # raw caller request, before default-latest resolution
    requested_revision = revision
    key = _idempotency_key(campaign.id, occurrence_key, range_generation_ref)
    now = timezone.now()

    # Target set is immutable after authoring, so the ids can be read before locking.
    target_event_ids = list(campaign.target_events.values_list("id", flat=True))

    with transaction.atomic():
        # 1. Lock the live target events in primary-key order (canonical order shared
        #    with lifecycle) so a concurrent cancellation/fence cannot interleave.
        target_events = list(CTFEvent.objects.select_for_update().filter(id__in=target_event_ids).order_by("pk"))

        # 2. Re-check live authority inside the locked transaction -- on every caller,
        #    replay included -- so a revoked/unauthorized/token actor admits no work.
        reauthorize(campaign, target_events, actor)

        # 3. Lock the campaign for the idempotency/replay decision.
        locked = CommunicationCampaign.objects.select_for_update().get(pk=campaign.pk)
        existing = CommunicationIntent.objects.filter(idempotency_key=key).first()
        if existing is not None:
            if existing.campaign_id != locked.pk:
                raise CTFCommunicationError(
                    "Idempotency identity does not match this campaign",
                    code="CTF_COMMUNICATION_IDEMPOTENCY_MISMATCH",
                )
            _assert_replay_matches(existing, requested_revision=requested_revision, requested_due_at=None, actor=actor)
            return existing

        # Occurrence gate: a supported kind is not enough -- the declared occurrence
        # must actually have happened before any audience is materialized.
        assert_occurrence_ready(locked, target_events, now=now, immediate=True, allow_early=actor.allow_early_release)
        _assert_release_allowed(locked, target_events)
        revision = _resolve_revision(locked, revision)
        recipients = resolve_recipients(set(target_event_ids), locked.audience_spec)
        channels = list(locked.channels)
        attribution_user_id = actor.user_id if actor.user_id is not None else locked.created_by_id
        attribution_token_id = actor.token_id if actor.token_id is not None else locked.actor_token_id
        workspace_id = _legacy_workspace_id(locked)

        # Backpressure runs only on genuine (non-replay) admission -- the replay
        # check above already returned -- so a retry never double-reserves capacity.
        enforce_admission(
            AdmissionRequest(
                actor_user_id=attribution_user_id,
                workspace_id=workspace_id,
                event_ids=frozenset(target_event_ids),
                audience_size=len(recipients),
                channel_count=len(channels),
            )
        )

        try:
            # Nested savepoint: a uniqueness race raises IntegrityError against the
            # savepoint only, so the OUTER transaction stays usable to query the
            # winning row (never a query inside a broken atomic block).
            with transaction.atomic():
                intent = CommunicationIntent.objects.create(
                    campaign=locked,
                    revision=revision,
                    status=IntentStatus.RELEASED.value,
                    trigger_kind=locked.trigger_spec["kind"],
                    origin=locked.origin,
                    actor_user_id=attribution_user_id,
                    actor_token_id=attribution_token_id,
                    channels=channels,
                    acknowledgement_policy=locked.acknowledgement_policy,
                    occurrence_key=occurrence_key,
                    idempotency_key=key,
                    range_generation_ref=range_generation_ref,
                    released_at=now,
                )
        except IntegrityError:
            committed = CommunicationIntent.objects.filter(idempotency_key=key, campaign=locked).first()
            if committed is not None:
                _assert_replay_matches(
                    committed, requested_revision=requested_revision, requested_due_at=None, actor=actor
                )
                return committed
            raise

        _materialize(intent, recipients, channels, now)
        CommunicationCampaign.objects.filter(pk=locked.pk).update(status=CampaignStatus.RELEASED.value, updated_at=now)
        audit_communication_release(
            actor_id=intent.actor_user_id,
            campaign_id=locked.id,
            intent_id=intent.id,
            workspace_id=workspace_id,
            recipient_count=len(recipients),
            channels=channels,
        )
    logger.info(
        "Released communication intent %s for campaign %s (%d recipients)",
        intent.id,
        campaign.id,
        len(recipients),
    )
    return intent


# Outcomes of a due-time release attempt. RELEASED/EXPIRED are terminal for the
# declaration; NOT_DUE means the occurrence is not yet due (early tick / backward
# clock jump) and must be retried; NOOP means the declaration was already
# released, cancelled, or fenced and there is no new work.
RELEASE_OUTCOME_RELEASED = "released"
RELEASE_OUTCOME_EXPIRED = "expired"
RELEASE_OUTCOME_NOT_DUE = "not_due"
RELEASE_OUTCOME_NOOP = "noop"


def _classify_due(intent: CommunicationIntent, now: datetime, allow_early: bool) -> str | None:
    """Classify a locked scheduled intent's due-time disposition.

    Returns a terminal ``RELEASE_OUTCOME_*`` when no materialization should happen
    (already released, not schedulable work, not yet due, or past the grace window),
    or ``None`` when the caller should proceed to materialize the audience.
    """
    if intent.status == IntentStatus.RELEASED.value:
        outcome: str | None = RELEASE_OUTCOME_RELEASED
    elif intent.status != IntentStatus.SCHEDULED.value:
        # cancelled / fenced / already expired
        outcome = RELEASE_OUTCOME_NOOP
    elif intent.due_at is not None and not allow_early and now < intent.due_at:
        outcome = RELEASE_OUTCOME_NOT_DUE
    elif (
        intent.due_at is not None
        and not allow_early
        and now > intent.due_at + timedelta(minutes=settings.CTF_COMMUNICATION_RELEASE_GRACE_MINUTES)
    ):
        outcome = RELEASE_OUTCOME_EXPIRED
    else:
        outcome = None
    return outcome


def release_due_declaration(
    intent: CommunicationIntent,
    *,
    actor: AdmissionActor,
    now: datetime | None = None,
    allow_early: bool = False,
) -> str:
    """Materialize a SCHEDULED intent's audience at its due occurrence.

    This is the due-time half of the one admission transaction: it locks the live
    target events (primary-key order), re-checks authority for the declaration's
    stored ``actor`` (a revoked human actor, or any token actor, admits no work),
    then applies the closed lateness policy and, when in window, resolves and
    materializes the audience and transitions the intent SCHEDULED -> RELEASED.

    Idempotent for repeated ticks / run-now / restart: an already-RELEASED intent
    is observed (not re-materialized), and a CANCELLED/FENCED/EXPIRED intent is a
    no-op. Past the bounded grace window the intent becomes EXPIRED (a durable
    no-work outcome, never a late delivery, never FENCED). ``allow_early`` releases
    before the due time for an authorized organizer run-now. Returns one of the
    ``RELEASE_OUTCOME_*`` constants.
    """
    now = now or timezone.now()
    campaign = intent.campaign
    assert_source_realizable(campaign.trigger_spec["kind"])
    target_event_ids = list(campaign.target_events.values_list("id", flat=True))

    with transaction.atomic():
        target_events = list(CTFEvent.objects.select_for_update().filter(id__in=target_event_ids).order_by("pk"))
        reauthorize(campaign, target_events, actor)
        locked_campaign = CommunicationCampaign.objects.select_for_update().get(pk=campaign.pk)
        locked_intent = CommunicationIntent.objects.select_for_update().get(pk=intent.pk)

        disposition = _classify_due(locked_intent, now, allow_early)
        if disposition is not None:
            if disposition == RELEASE_OUTCOME_EXPIRED:
                CommunicationIntent.objects.filter(pk=locked_intent.pk).update(
                    status=IntentStatus.EXPIRED.value, updated_at=now
                )
                logger.info("Scheduled communication intent %s expired past its grace window", locked_intent.id)
            return disposition

        _assert_release_allowed(locked_campaign, target_events)
        recipients = resolve_recipients(set(target_event_ids), locked_campaign.audience_spec)
        channels = list(locked_intent.channels)
        workspace_id = _legacy_workspace_id(locked_campaign)
        enforce_admission(
            AdmissionRequest(
                actor_user_id=locked_intent.actor_user_id
                if locked_intent.actor_user_id is not None
                else locked_campaign.created_by_id,
                workspace_id=workspace_id,
                event_ids=frozenset(target_event_ids),
                audience_size=len(recipients),
                channel_count=len(channels),
            )
        )
        _materialize(locked_intent, recipients, channels, now)
        CommunicationIntent.objects.filter(pk=locked_intent.pk).update(
            status=IntentStatus.RELEASED.value, released_at=now, updated_at=now
        )
        CommunicationCampaign.objects.filter(pk=locked_campaign.pk).update(
            status=CampaignStatus.RELEASED.value, updated_at=now
        )
        audit_communication_release(
            actor_id=locked_intent.actor_user_id,
            campaign_id=locked_campaign.id,
            intent_id=locked_intent.id,
            workspace_id=workspace_id,
            recipient_count=len(recipients),
            channels=channels,
        )
    logger.info("Released scheduled communication intent %s at due time (%d recipients)", intent.id, len(recipients))
    return RELEASE_OUTCOME_RELEASED
