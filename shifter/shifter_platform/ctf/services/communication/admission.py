"""Live re-authorization for the one communication admission transaction (#2099).

Every trigger source normalizes a bounded declaration and then enters this single
admission path. Admission re-derives authority server-side and re-checks it
against the live actor / token / workspace / target events INSIDE the locked
release transaction — never trusting origin, actor, token, or scope supplied by a
request or scheduler metadata — so revoked or unauthorized principals admit
no new work (ADR-051-R12, AC3).

Token actors require the original live owner/token pair and the exact communication
scope; neither event scopes nor system authority substitute for that identity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model

import workspaces.services as workspace_services
from ctf.enums import EventCapability
from ctf.enums_communication import TriggerKind
from ctf.exceptions import CTFCommunicationError
from ctf.services.authorization import resolve_event_authority
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import CTF_COMMUNICATION_WRITE, has_scope

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from ctf.models import CommunicationCampaign, CTFEvent

logger = logging.getLogger(__name__)

# Trigger sources whose realization exists in this slice: an organizer session
# (manual), an organizer-authored absolute UTC schedule, and a trusted system
# milestone (event lifecycle). A new source is added at this validated seam.
SUPPORTED_TRIGGER_KINDS = frozenset(
    {TriggerKind.MANUAL.value, TriggerKind.EVENT_LIFECYCLE.value, TriggerKind.ABSOLUTE_TIME.value}
)
# Sources whose realization consumes a RAES interpreter / CMS generation projection
# that is provisioning-only at this baseline. Per ADR-051-R12 unsupported
# realization stays CLOSED (fail-closed) rather than being approximated as an
# absolute timestamp or a range-instance id; they are enabled by later slices.
CLOSED_TRIGGER_KINDS = frozenset({TriggerKind.RAES_OCCURRENCE.value, TriggerKind.RANGE_SIGNAL.value})


def assert_source_realizable(trigger_kind: str) -> None:
    """Fail-closed for a trigger source whose realization is not available yet.

    Called at the head of every admission entry (release and schedule) so an
    unsupported source admits no work for any caller, including replay.
    """
    if trigger_kind in CLOSED_TRIGGER_KINDS:
        raise CTFCommunicationError(
            "This communication trigger source is not available yet",
            code="CTF_COMMUNICATION_SOURCE_CLOSED",
        )
    if trigger_kind not in SUPPORTED_TRIGGER_KINDS:
        raise CTFCommunicationError("Unknown communication trigger source", code="CTF_COMMUNICATION_SOURCE_UNKNOWN")


def _parse_trigger_due(trigger: dict[str, Any]) -> datetime:
    """Parse a trigger's already-normalized UTC ``due_at`` into an aware datetime."""
    return datetime.fromisoformat(trigger["due_at"])


def assert_occurrence_ready(
    campaign: CommunicationCampaign,
    target_events: list[CTFEvent],
    *,
    now: datetime,
    immediate: bool,
    due_at: datetime | None = None,
    allow_early: bool = False,
) -> None:
    """Enforce the source-specific occurrence condition at the admission boundary.

    ``assert_source_realizable`` only proves the trigger *kind* is supported; this
    proves the declared *occurrence* has actually happened before any audience is
    materialized (#2099), so a future absolute-time campaign cannot be released
    immediately, a scheduled due time cannot diverge from the campaign's authored
    trigger, and a lifecycle campaign cannot release before its milestone.

    ``immediate`` is True for a release-now path and False for a schedule path.
    ``allow_early`` (authorized organizer run-now) waives the not-yet-due check.
    """
    trigger = campaign.trigger_spec
    kind = trigger.get("kind")
    if kind == TriggerKind.MANUAL.value:
        # the occurrence is the manual action itself
        return
    if kind == TriggerKind.ABSOLUTE_TIME.value:
        trigger_due = _parse_trigger_due(trigger)
        if immediate:
            if not allow_early and now < trigger_due:
                raise CTFCommunicationError(
                    "This timed communication is not yet due; schedule it instead",
                    code="CTF_COMMUNICATION_NOT_DUE",
                )
        elif due_at is None or due_at != trigger_due:
            raise CTFCommunicationError(
                "Scheduled due time does not match the campaign's absolute-time trigger",
                code="CTF_COMMUNICATION_DUE_MISMATCH",
            )
        return
    if kind == TriggerKind.EVENT_LIFECYCLE.value:
        if not immediate:
            raise CTFCommunicationError(
                "An event-lifecycle communication fires on its milestone, not a clock schedule",
                code="CTF_COMMUNICATION_LIFECYCLE_NOT_SCHEDULABLE",
            )
        declared = trigger.get("event_status")
        if any(event.status != declared for event in target_events):
            raise CTFCommunicationError(
                "The event-lifecycle milestone has not occurred on every target event",
                code="CTF_COMMUNICATION_MILESTONE_NOT_REACHED",
            )
    # Closed kinds are already rejected by assert_source_realizable.


@dataclass(frozen=True, slots=True)
class AdmissionActor:
    """Who is admitting a communication, proven server-side by the caller.

    Exactly one authority mode is honored, in precedence order:

    - ``token_id`` — a scheduled / token-authored declaration. The original user
      and token must remain eligible with the exact communication scope.
    - ``system`` — trusted lifecycle / lease automation (event-lifecycle
      milestones, generation-bound range signals). Admitted without a live human
      actor, but only when a source normalizer has proven the trust boundary and
      set this flag explicitly; a merely-missing actor is never system authority.
    - ``user_id`` — a live session actor (human-authored). Re-checked against the
      active user row, the bound-workspace mutex, and per-event notification
      authority.

    ``allow_early_release`` authorizes releasing a scheduled declaration before its
    due time (organizer run-now); it is honored only on the live-session path.
    """

    user_id: int | None = None
    token_id: int | None = None
    system: bool = False
    allow_early_release: bool = False
    request_id: str = ""


def _live_actor(user_id: int) -> User:
    """Return the active user row for ``user_id`` or deny (revoked/inactive/absent)."""
    user = get_user_model().objects.select_for_update().filter(pk=user_id, is_active=True).first()
    profile = getattr(user, "profile", None)
    if user is None or getattr(profile, "deleted_at", None) or getattr(profile, "is_ctf_account", False):
        raise CTFCommunicationError("Communication actor is not active", code="CTF_COMMUNICATION_ACTOR_DENIED")
    return user


def _assert_target_set(campaign: CommunicationCampaign, target_events: list[CTFEvent]) -> None:
    """Reject empty, deleted, cross-workspace or incomplete target sets."""
    if not target_events or any(
        event.workspace_id != campaign.workspace_id or event.deleted_at is not None for event in target_events
    ):
        raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_TARGET_DENIED")
    if not campaign._state.adding and len(target_events) != campaign.target_event_links.count():
        raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_TARGET_DENIED")


def _authorize_token(actor: AdmissionActor, required_scope: str) -> None:
    """Lock and validate the original token-owner pair and exact scope."""
    if actor.token_id is not None:
        token = ApiToken.objects.select_for_update().filter(pk=actor.token_id).first()
        if (
            token is None
            or actor.user_id is None
            or token.created_by_id != actor.user_id
            or not token.is_active
            or not token.has_eligible_owner
            or not has_scope(token.scopes, required_scope)
            or actor.system
            or actor.allow_early_release
        ):
            raise CTFCommunicationError("Communication token is not authorized", code="CTF_COMMUNICATION_TOKEN_DENIED")


def reauthorize(
    campaign: CommunicationCampaign,
    target_events: list[CTFEvent],
    actor: AdmissionActor,
    *,
    required_scope: str = CTF_COMMUNICATION_WRITE,
    audit_authority: bool = True,
    operation: str = "admit",
) -> None:
    """Re-check live authority for ``actor`` inside the locked admission transaction.

    ``target_events`` and ``campaign`` are already row-locked by the caller, and
    this runs inside ``transaction.atomic()`` so the workspace-membership mutex is
    held until the release commits: a concurrent membership revocation either has
    already committed (and this denies) or blocks behind the lock until the release
    transaction finishes. Raises ``CTFCommunicationError`` on any denial and
    returns ``None`` when admission may proceed.
    """
    _assert_target_set(campaign, target_events)
    if actor.system and actor.token_id is None:
        return
    if actor.user_id is None:
        raise CTFCommunicationError("A communication actor is required", code="CTF_COMMUNICATION_ACTOR_REQUIRED")
    user = _live_actor(actor.user_id)
    _authorize_token(actor, required_scope)
    try:
        workspace_services.authorize_launch_workspace_locked(
            user, campaign.workspace_id, workspace_services.WorkspaceOperation.USE_CTF_COMMUNICATIONS
        )
    except workspace_services.WorkspaceAuthorizationError as exc:
        raise CTFCommunicationError(
            "Workspace is not available for CTF communications",
            code="CTF_COMMUNICATION_WORKSPACE_DENIED",
        ) from exc
    for event in target_events:
        authority = resolve_event_authority(user, event, capability=EventCapability.NOTIFICATIONS.value)
        if authority is None:
            raise CTFCommunicationError(
                "Actor lacks notification authority on a target event",
                code="CTF_COMMUNICATION_EVENT_DENIED",
            )
        if audit_authority and required_scope == CTF_COMMUNICATION_WRITE:
            from ctf.services.communication.audit import audit_communication_authority

            audit_communication_authority(
                event_id=event.pk,
                actor_id=user.pk,
                token_id=actor.token_id,
                authority_source=authority.value,
                request_id=actor.request_id,
                operation=operation,
            )


def lock_authorized_campaign(
    campaign: CommunicationCampaign, actor: AdmissionActor, *, operation: str = "update"
) -> CommunicationCampaign:
    """Serialize every authoring mutation in the release/lifecycle lock order."""
    from ctf.models import CommunicationCampaign, CTFEvent

    events = list(
        CTFEvent.objects.select_for_update().filter(communication_target_links__campaign=campaign).order_by("pk")
    )
    locked = CommunicationCampaign.objects.select_for_update().get(pk=campaign.pk)
    reauthorize(locked, events, actor, operation=operation)
    return locked
