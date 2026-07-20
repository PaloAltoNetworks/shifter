"""Idempotent, checkpointed steps of participant range recovery (issue #1018).

Split out of :mod:`ctf.services.range.recovery` (Sonar S104). Each step is
resume-safe: it derives "already done" from the recorded recovery *data*, so a
retry after a crash never repeats a completed side effect. Orchestration,
claiming, and failure classification stay in the parent module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from ctf.enums import RecoveryFailureCategory, RecoveryPhase, SpareRangeStatus
from ctf.exceptions import CTFRangeError, CTFValidationError
from ctf.models import CTFParticipant, CTFRangeRecovery, CTFSpareRange
from ctf.services.audit import audit_range_recovery
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# Range statuses that mean "already torn down" -- teardown is a no-op for these.
_OLD_RANGE_TERMINAL_STATUSES = {ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value}


def _range_error(message: str, *, category: RecoveryFailureCategory, **details: Any) -> CTFRangeError:
    """Build a `CTFRangeError` carrying an authored failure category for classification."""
    details = {**details, "failure_category": category.value}
    return CTFRangeError(message, details=details)


def _participant_user(participant: CTFParticipant) -> User:
    """Return the participant's user (guaranteed set by :func:`_claim_recovery`).

    ``CTFParticipant.user`` is nullable at the model level, but the recovery
    workflow only proceeds past :func:`_claim_recovery` for a registered
    participant. This re-narrows that invariant for the type checker (and
    fails loudly rather than passing ``None`` to a downstream boundary).
    """
    user = participant.user
    if user is None:
        raise CTFValidationError(
            "Participant must be registered before range recovery",
            details={
                "participant_id": str(participant.pk),
                "failure_category": RecoveryFailureCategory.VALIDATION_FAILED.value,
            },
        )
    return user


def _rebuild_replacement(participant: CTFParticipant) -> tuple[int, UUID]:
    """Provision a fresh replacement range via the normal CTF/CMS bridge."""
    from ctf.bridges import cms_create_range, cms_find_range_instance_id

    user = _participant_user(participant)
    event = participant.event
    agents_by_os = event.range_config.get("agents_by_os", {}) if event.range_config else {}
    ngfw_enabled = event.range_config.get("ngfw_enabled", False) if event.range_config else False

    try:
        result = cms_create_range(
            user=user,
            scenario=event.scenario_id,
            agents_by_os=agents_by_os,
            ngfw_enabled=ngfw_enabled,
            remote_access_teardown_at=event.get_cleanup_time(),
        )
    except Exception as e:
        raise _range_error(
            f"Replacement range provisioning failed: {e}",
            category=RecoveryFailureCategory.PROVISIONING_FAILED,
            participant_id=str(participant.pk),
        ) from e

    replacement_id = cms_find_range_instance_id(result.request_id)
    if replacement_id is None:
        raise _range_error(
            "Replacement range was created but its instance id could not be resolved",
            category=RecoveryFailureCategory.PROVISIONING_FAILED,
            participant_id=str(participant.pk),
            request_id=str(result.request_id),
        )
    return replacement_id, result.request_id


def _claim_spare(participant: CTFParticipant, spare_range_instance_id: int | None) -> CTFSpareRange | None:
    """Durably reserve a compatible spare from the participant's event pool, or `None`.

    Selects a READY, unconsumed, event-scoped spare ``FOR UPDATE`` and marks it
    CONSUMED so a concurrent recovery cannot take it -- a query-only check would
    race (a competitor could consume it between check and attach, after this
    recovery destroyed the old range, stranding the participant, #307 review).
    Event scoping (the ``CTFSpareRange.event`` FK) is the tenant boundary even
    for an explicitly named spare; a stale-local-status spare is confirmed
    live-READY via the bridge first. Ownership moves later, in
    :func:`_ensure_spare_attached` (after teardown), per the #307 constraint.
    MUST run inside the caller's transaction (``select_for_update``);
    :func:`_ensure_spare_reserved` wraps this claim and the pointer write atomically.
    """
    from ctf.bridges import cms_get_range_status, cms_range_owner_reassignment_available

    event = participant.event
    candidates = (
        CTFSpareRange.objects.select_for_update()
        .filter(event=event, consumed_by__isnull=True)
        .exclude(status=SpareRangeStatus.FAILED.value)
    )
    if spare_range_instance_id is not None:
        candidates = candidates.filter(range_instance_id=spare_range_instance_id)

    for candidate in candidates.order_by("-created_at"):
        if candidate.range_instance_id is None:
            continue
        live_ready = candidate.status == SpareRangeStatus.READY.value or (
            cms_get_range_status(candidate.range_instance_id) == ResourceStatus.READY.value
        )
        if not live_ready:
            continue
        if not cms_range_owner_reassignment_available(candidate.range_instance_id):
            continue
        candidate.consumed_by = participant
        candidate.consumed_at = timezone.now()
        candidate.status = SpareRangeStatus.CONSUMED.value
        candidate.save(update_fields=["consumed_by", "consumed_at", "status", "updated_at"])
        return candidate
    return None


def _ensure_spare_reserved(
    recovery: CTFRangeRecovery, participant: CTFParticipant, spare_range_instance_id: int | None
) -> None:
    """Reserve the replacement spare before any teardown (idempotent).

    Records the claimed spare id (a resume reuses it). Raising (no spare) happens
    BEFORE teardown, so a missing spare never strands the participant (#1018).
    """
    if recovery.replacement_range_instance_id is not None:
        return
    # Claim + record the pointer in ONE transaction: a crash between them rolls
    # both back, so a spare is never CONSUMED without a durable recovery pointer.
    with transaction.atomic():
        spare = _claim_spare(participant, spare_range_instance_id)
        if spare is None:
            raise _range_error(
                "No compatible spare range available for reassignment",
                category=RecoveryFailureCategory.NO_COMPATIBLE_SPARE,
                participant_id=str(participant.pk),
                event_id=str(participant.event_id),
            )
        recovery.replacement_range_instance_id = spare.range_instance_id
        recovery.save(update_fields=["replacement_range_instance_id", "updated_at"])


def _ensure_spare_attached(recovery: CTFRangeRecovery, participant: CTFParticipant) -> None:
    """Attach the reserved spare after the old range is blocked (idempotent, #307).

    ``cms_reassign_range_owner`` is a no-op when already owned (resume safe);
    the freed managed spare user is deleted once.
    """
    from ctf.bridges import cms_reassign_range_owner
    from ctf.services.range.spares import delete_managed_spare_user

    replacement_id = recovery.replacement_range_instance_id
    if replacement_id is None:
        raise _range_error(
            "Reserved replacement range id missing during attach",
            category=RecoveryFailureCategory.INTERNAL_ERROR,
            recovery_id=str(recovery.pk),
        )

    cms_reassign_range_owner(replacement_id, _participant_user(participant))

    spare = CTFSpareRange.objects.filter(range_instance_id=replacement_id).first()
    if spare is not None and spare.owner_user_id is not None:
        freed_owner = spare.owner_user
        spare.owner_user = None
        spare.save(update_fields=["owner_user", "updated_at"])
        delete_managed_spare_user(freed_owner)

    recovery.phase = RecoveryPhase.REPLACEMENT_READY.value
    recovery.save(update_fields=["phase", "updated_at"])


def _ensure_rebuild_replacement_ready(recovery: CTFRangeRecovery, participant: CTFParticipant) -> None:
    """Provision a fresh rebuild replacement range (idempotent; rebuild-only).

    reassign_spare reserves via :func:`_ensure_spare_reserved` before teardown.
    """
    if recovery.replacement_range_instance_id is not None:
        return
    replacement_id, replacement_request_id = _rebuild_replacement(participant)

    recovery.replacement_range_instance_id = replacement_id
    recovery.replacement_request_id = replacement_request_id
    recovery.phase = RecoveryPhase.REPLACEMENT_READY.value
    recovery.save(update_fields=["replacement_range_instance_id", "replacement_request_id", "phase", "updated_at"])


def _ensure_old_range_blocked(recovery: CTFRangeRecovery, old_range_instance_id: int, user: User) -> None:
    """Tear down the old range unless it is already in a terminal state.

    Idempotent against retries: ``cms.services.destroy_range`` is not itself
    safely re-callable on an already-soft-deleted range (it raises "not
    found"), so the live status is checked first via
    ``ctf.bridges.cms_get_range_status`` before dispatching teardown.
    """
    from ctf.bridges import cms_destroy_range, cms_get_range_status

    current_status = cms_get_range_status(old_range_instance_id)
    if current_status not in _OLD_RANGE_TERMINAL_STATUSES:
        try:
            cms_destroy_range(user, old_range_instance_id)
        except Exception as e:
            raise _range_error(
                f"Failed to block old range {old_range_instance_id}: {e}",
                category=RecoveryFailureCategory.OLD_RANGE_TEARDOWN_FAILED,
                old_range_instance_id=old_range_instance_id,
            ) from e

    recovery.phase = RecoveryPhase.OLD_RANGE_BLOCKED.value
    recovery.save(update_fields=["phase", "updated_at"])


def _ensure_participant_repointed(participant: CTFParticipant, recovery: CTFRangeRecovery) -> None:
    """Idempotency is data-driven: skip the write once already pointed at the replacement."""
    from ctf.bridges import cms_get_range_status

    replacement_id = recovery.replacement_range_instance_id
    if replacement_id is None:
        # The replacement id is recorded first (reserve / rebuild-ready step).
        raise _range_error(
            "Replacement range id missing during repoint",
            category=RecoveryFailureCategory.INTERNAL_ERROR,
            recovery_id=str(recovery.pk),
        )

    participant.refresh_from_db()
    if participant.range_instance_id != replacement_id:
        replacement_status = cms_get_range_status(replacement_id)
        participant.range_instance_id = replacement_id
        participant.range_status = replacement_status
        participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])

    recovery.phase = RecoveryPhase.PARTICIPANT_REPOINTED.value
    recovery.save(update_fields=["phase", "updated_at"])


def _complete_recovery(
    recovery: CTFRangeRecovery,
    participant: CTFParticipant,
    operator: User | None,
) -> None:
    """Write the completion audit row and mark `recovery` as `COMPLETED`."""
    audit_range_recovery(
        actor_id=operator.id if operator is not None else None,
        recovery=recovery,
        participant=participant,
        previous_status=ResourceStatus.DESTROYING.value,
    )
    recovery.phase = RecoveryPhase.COMPLETED.value
    recovery.save(update_fields=["phase", "updated_at"])
