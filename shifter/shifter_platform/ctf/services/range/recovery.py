"""Destroyed-participant-range recovery (issue #1018).

Recovers one CTF participant's live-fire range when it is beyond in-place
repair, either by rebuilding a fresh same-event/same-scenario range or by
reassigning ownership of a prewarmed spare range from the event's spare pool
(:mod:`ctf.services.range.spares`), while preserving the participant's
identity, submissions, awards, team/bracket membership, and registration
state untouched. The old range is always destroyed -- there is no
disposition/forensics-retention concept (owner decision, #1018 revised plan).

The workflow is phase-checkpointed and idempotent: :class:`~ctf.models.CTFRangeRecovery`
records the recovery intent (keyed on participant + old range + strategy) and
its progress. Resumption on retry is driven by the recorded
replacement/teardown *data* (not solely by ``phase``, which is overwritten to
``failed`` on any exception and is otherwise observability-only), so a crash
partway through never re-runs an already-completed step or duplicates the
replacement range or the audit row.

Both strategies block the old range before attaching the replacement, because
CMS admits only one active range per source per user (#450's
``_assert_no_active_range``, hardened into a DB constraint by #307). So
``reassign_spare`` durably reserves a compatible spare (an atomic ``FOR UPDATE``
claim a competing recovery cannot take) before teardown -- keeping #1018's
no-stranding guarantee -- and moves ownership only after the old range is blocked.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

from ctf.enums import RecoveryFailureCategory, RecoveryPhase, RecoveryStrategy
from ctf.exceptions import CTFError, CTFNotFoundError, CTFRangeError, CTFValidationError
from ctf.models import CTFParticipant, CTFRangeRecovery
from ctf.services.range.recovery_steps import (
    _complete_recovery,
    _ensure_old_range_blocked,
    _ensure_participant_repointed,
    _ensure_rebuild_replacement_ready,
    _ensure_spare_attached,
    _ensure_spare_reserved,
    _participant_user,
)
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = {s.value for s in RecoveryStrategy}


def _validate_strategy(strategy: str) -> None:
    """Raise `CTFValidationError` if `strategy` is not a recognized `RecoveryStrategy` value."""
    if strategy not in _VALID_STRATEGIES:
        raise CTFValidationError(
            f"Invalid recovery strategy: {strategy!r}",
            details={"strategy": str(strategy), "failure_category": RecoveryFailureCategory.VALIDATION_FAILED.value},
        )


def _claim_recovery(
    participant_id: UUID,
    strategy: str,
    operator: User | None,
) -> tuple[CTFParticipant, CTFRangeRecovery, int]:
    """Lock the participant, validate inputs, and get-or-create the recovery intent row.

    No ``select_related``: ``user`` is nullable (``FOR UPDATE`` rejects the
    nullable side of an outer join on PostgreSQL) and joining ``event`` would
    widen the lock to an event-wide row lock -- both load lazily under the
    lock, mirroring ``ctf.services.range.provision.provision_participant_range``.
    """
    with transaction.atomic():
        try:
            participant = CTFParticipant.objects.select_for_update().get(pk=participant_id)
        except CTFParticipant.DoesNotExist:
            raise CTFNotFoundError(
                f"Participant {participant_id} not found",
                details={"participant_id": str(participant_id)},
            ) from None

        if participant.user_id is None:
            raise CTFValidationError(
                "Participant must be registered before range recovery",
                details={
                    "participant_id": str(participant_id),
                    "failure_category": RecoveryFailureCategory.VALIDATION_FAILED.value,
                },
            )

        old_range_instance_id = participant.range_instance_id
        if old_range_instance_id is None:
            raise CTFRangeError(
                "Participant has no range assigned to recover",
                details={
                    "participant_id": str(participant_id),
                    "failure_category": RecoveryFailureCategory.VALIDATION_FAILED.value,
                },
            )

        _validate_strategy(strategy)

        recovery, created = CTFRangeRecovery.objects.get_or_create(
            participant=participant,
            old_range_instance_id=old_range_instance_id,
            strategy=strategy,
            defaults={
                "event": participant.event,
                "created_by": operator,
            },
        )
        if created:
            logger.info(
                "recover_participant_range: opened recovery=%s participant=%s strategy=%s",
                recovery.pk,
                safe_log_value(participant_id),
                safe_log_value(strategy),
            )
        else:
            logger.info(
                "recover_participant_range: resuming recovery=%s phase=%s",
                recovery.pk,
                recovery.phase,
            )

    return participant, recovery, old_range_instance_id


def _failure_category_from_exception(exc: Exception) -> RecoveryFailureCategory:
    """Map a raised exception's authored `failure_category` detail to a `RecoveryFailureCategory`.

    Falls back to `INTERNAL_ERROR` when the exception carries no such detail.
    """
    details = getattr(exc, "details", None) or {}
    raw = details.get("failure_category")
    if raw:
        try:
            return RecoveryFailureCategory(raw)
        except ValueError:
            pass
    return RecoveryFailureCategory.INTERNAL_ERROR


def _mark_recovery_failed(recovery: CTFRangeRecovery, exc: Exception) -> None:
    """Classify `exc` and record `recovery` as `FAILED` with that failure category."""
    category = _failure_category_from_exception(exc)
    logger.error(
        "recover_participant_range: recovery=%s failed category=%s detail=%s",
        recovery.pk,
        category.value,
        safe_log_value(str(exc)),
    )
    recovery.phase = RecoveryPhase.FAILED.value
    recovery.failure_category = category.value
    recovery.save(update_fields=["phase", "failure_category", "updated_at"])


def _recovery_result(recovery: CTFRangeRecovery) -> dict[str, Any]:
    """Serialize `recovery` into the API/service-layer result dict (see `get_recovery_status`)."""
    return {
        "recovery_id": str(recovery.pk),
        "participant_id": str(recovery.participant_id),
        "event_id": str(recovery.event_id),
        "old_range_instance_id": recovery.old_range_instance_id,
        "replacement_range_instance_id": recovery.replacement_range_instance_id,
        "replacement_request_id": (str(recovery.replacement_request_id) if recovery.replacement_request_id else None),
        "strategy": recovery.strategy,
        "phase": recovery.phase,
        "failure_category": recovery.failure_category,
    }


def recover_participant_range(
    participant_id: UUID,
    *,
    strategy: str,
    operator: User,
    spare_range_instance_id: int | None = None,
) -> dict[str, Any]:
    """Recover a participant's range that is beyond in-place repair.

    Both strategies block the old range before attaching the replacement (see
    the module docstring): CMS admits only one active range per source per user
    (#450, a DB constraint under #307). ``reassign_spare`` durably reserves its
    spare (an atomic claim) before teardown so a missing spare never strands the
    participant. The old range is always destroyed -- there is no
    disposition/forensics-retention choice.

    Args:
        participant_id: UUID of the participant whose range is being recovered.
        strategy: ``"rebuild"`` or ``"reassign_spare"``
            (see :class:`~ctf.enums.RecoveryStrategy`).
        operator: The organizer/operator initiating the recovery (audit actor
            and ``CTFRangeRecovery.created_by``).
        spare_range_instance_id: When ``strategy == "reassign_spare"``, an
            operator-chosen spare (from the participant's own event pool) to
            validate and use instead of auto-discovering one.

    Returns:
        Dict describing the recovery record (see :func:`get_recovery_status`).

    Raises:
        CTFNotFoundError: If the participant does not exist.
        CTFValidationError: If the participant is unregistered or the
            strategy is not a recognized choice.
        CTFRangeError: If the participant has no range to recover, no
            compatible spare is available, replacement provisioning fails, or
            old-range teardown fails.
    """
    logger.info(
        "recover_participant_range: participant=%s strategy=%s",
        safe_log_value(participant_id),
        safe_log_value(strategy),
    )

    participant, recovery, old_range_instance_id = _claim_recovery(participant_id, strategy, operator)

    if recovery.phase == RecoveryPhase.COMPLETED.value:
        logger.info("recover_participant_range: recovery=%s already completed", recovery.pk)
        return _recovery_result(recovery)

    try:
        # Both strategies block the old range before attaching the replacement
        # (#307 one-active-range-per-source; see the module docstring).
        if strategy == RecoveryStrategy.REBUILD.value:
            _ensure_old_range_blocked(recovery, old_range_instance_id, _participant_user(participant))
            _ensure_rebuild_replacement_ready(recovery, participant)
        else:
            # reassign_spare reserves the spare before teardown (no stranding).
            _ensure_spare_reserved(recovery, participant, spare_range_instance_id)
            _ensure_old_range_blocked(recovery, old_range_instance_id, _participant_user(participant))
            _ensure_spare_attached(recovery, participant)
        _ensure_participant_repointed(participant, recovery)
        _complete_recovery(recovery, participant, operator)
    except Exception as exc:
        _mark_recovery_failed(recovery, exc)
        if isinstance(exc, CTFError):
            raise
        logger.exception("recover_participant_range: unexpected failure recovery=%s", recovery.pk)
        raise CTFRangeError(
            f"Range recovery failed: {exc}",
            details={
                "participant_id": str(participant_id),
                "failure_category": RecoveryFailureCategory.INTERNAL_ERROR.value,
            },
        ) from exc

    return _recovery_result(recovery)


def get_recovery_status(participant_id: UUID) -> dict[str, Any] | None:
    """Return the latest range-recovery record for a participant, or None.

    Bounded operator diagnostics only (phase, strategy, replacement ids,
    authored failure category) -- never raw provider exceptions. Consumed by
    a later admin/Mission Control surface.
    """
    recovery = CTFRangeRecovery.objects.filter(participant_id=participant_id).order_by("-created_at").first()
    if recovery is None:
        return None
    return _recovery_result(recovery)
