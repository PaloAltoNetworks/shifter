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

Step ordering is strategy-dependent. ``reassign_spare`` prepares the
replacement (a different, already-existing range) before blocking the old
one, per the #1018 design note. ``rebuild`` cannot: CMS admits only one
active range per source per user (issue #450's ``_assert_no_active_range``),
so a same-user rebuild would collide with the still-active old range. For
``rebuild`` the old range is blocked first, then the replacement is built.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.enums import RecoveryFailureCategory, RecoveryPhase, RecoveryStrategy, SpareRangeStatus
from ctf.exceptions import CTFError, CTFNotFoundError, CTFRangeError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant, CTFRangeRecovery, CTFSpareRange
from ctf.services.audit import audit_range_recovery
from shared.enums import ResourceStatus
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = {s.value for s in RecoveryStrategy}

# Range statuses that mean "already torn down" -- teardown is a no-op for these.
_OLD_RANGE_TERMINAL_STATUSES = {ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value}


def _range_error(message: str, *, category: RecoveryFailureCategory, **details: Any) -> CTFRangeError:
    """Build a `CTFRangeError` carrying an authored failure category for classification."""
    details = {**details, "failure_category": category.value}
    return CTFRangeError(message, details=details)


def _validate_strategy(strategy: str) -> None:
    """Raise `CTFValidationError` if `strategy` is not a recognized `RecoveryStrategy` value."""
    if strategy not in _VALID_STRATEGIES:
        raise CTFValidationError(
            f"Invalid recovery strategy: {strategy!r}",
            details={"strategy": str(strategy), "failure_category": RecoveryFailureCategory.VALIDATION_FAILED.value},
        )


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


def _rebuild_replacement(participant: CTFParticipant) -> tuple[int, UUID]:
    """Provision a fresh replacement range via the normal CTF/CMS bridge."""
    from ctf.bridges import cms_create_range, cms_find_range_instance_id

    event = participant.event
    agents_by_os = event.range_config.get("agents_by_os", {}) if event.range_config else {}
    ngfw_enabled = event.range_config.get("ngfw_enabled", False) if event.range_config else False

    try:
        result = cms_create_range(
            user=participant.user,
            scenario=event.scenario_id,
            agents_by_os=agents_by_os,
            ngfw_enabled=ngfw_enabled,
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


def _find_available_spare(event: CTFEvent, spare_range_instance_id: int | None) -> CTFSpareRange | None:
    """Return the first available `CTFSpareRange` candidate for `event`, or `None`.

    A candidate must belong to *this* event (the ``CTFSpareRange.event`` FK is
    the tenant-isolation boundary -- a spare from a different event can never
    satisfy this query, even when named explicitly by
    ``spare_range_instance_id``, closing the #1018 review's cross-event
    range-takeover finding) and not already be consumed. Compatibility is
    scenario-implicit: a spare is only ever provisioned for its own event
    using ``event.scenario_id`` at creation time
    (:func:`ctf.services.range.spares.provision_event_spares`), so
    event-scoping alone establishes scenario compatibility.

    A spare's local ``status`` reaches ``ready`` via the
    ``cms.services.range_status_changed`` projection
    (:func:`ctf.signals.sync_ctf_spare_range_status`), which can lag the
    live CMS state, so a ``provisioning`` spare's live status is checked
    before it is discarded.
    """
    from ctf.bridges import cms_get_range_status

    candidates = CTFSpareRange.objects.filter(event=event, consumed_by__isnull=True).exclude(
        status=SpareRangeStatus.FAILED.value
    )
    if spare_range_instance_id is not None:
        candidates = candidates.filter(range_instance_id=spare_range_instance_id)

    for candidate in candidates.order_by("-created_at"):
        if candidate.range_instance_id is None:
            continue
        if candidate.status == SpareRangeStatus.READY.value:
            return candidate
        if cms_get_range_status(candidate.range_instance_id) == ResourceStatus.READY.value:
            return candidate
    return None


def _reassign_spare_replacement(participant: CTFParticipant, spare_range_instance_id: int | None) -> int:
    """Consume an available spare from the participant's own event pool.

    Reassigns the spare's CMS/engine ownership to the participant (terminal
    access is keyed on the range's owning user, so both must move together),
    marks the spare ``consumed``, and best-effort deletes its now-freed
    managed spare user.
    """
    from ctf.bridges import cms_reassign_range_owner
    from ctf.services.range.spares import delete_managed_spare_user

    event = participant.event
    spare = _find_available_spare(event, spare_range_instance_id)
    if spare is None:
        raise _range_error(
            "No compatible spare range available for reassignment",
            category=RecoveryFailureCategory.NO_COMPATIBLE_SPARE,
            participant_id=str(participant.pk),
            event_id=str(event.pk),
        )

    replacement_id = spare.range_instance_id
    # guaranteed by _find_available_spare
    assert replacement_id is not None
    cms_reassign_range_owner(replacement_id, _participant_user(participant))

    freed_owner = spare.owner_user
    spare.consumed_by = participant
    spare.consumed_at = timezone.now()
    spare.status = SpareRangeStatus.CONSUMED.value
    spare.owner_user = None
    spare.save(update_fields=["consumed_by", "consumed_at", "status", "owner_user", "updated_at"])
    delete_managed_spare_user(freed_owner)

    return replacement_id


def _ensure_replacement_ready(
    recovery: CTFRangeRecovery,
    participant: CTFParticipant,
    strategy: str,
    spare_range_instance_id: int | None,
) -> None:
    """Idempotency is data-driven: skip once a replacement id is already recorded."""
    if recovery.replacement_range_instance_id is not None:
        return

    if strategy == RecoveryStrategy.REBUILD.value:
        replacement_id, replacement_request_id = _rebuild_replacement(participant)
    else:
        replacement_id = _reassign_spare_replacement(participant, spare_range_instance_id)
        replacement_request_id = None

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
        # _ensure_replacement_ready always runs first and records the id.
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

    Step ordering is strategy-dependent (see the module docstring):
    ``reassign_spare`` prepares its replacement before blocking the old range;
    ``rebuild`` must block the old range first because CMS admits only one
    active range per source per user. The old range is always destroyed --
    there is no disposition/forensics-retention choice.

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
        if strategy == RecoveryStrategy.REBUILD.value:
            # CMS admits only one active range per source per user (#450), so a
            # same-user rebuild must block the old range before creating the
            # replacement -- unlike reassign_spare, which targets a different,
            # already-existing range and has no such collision.
            _ensure_old_range_blocked(recovery, old_range_instance_id, _participant_user(participant))
            _ensure_replacement_ready(recovery, participant, strategy, spare_range_instance_id)
        else:
            _ensure_replacement_ready(recovery, participant, strategy, spare_range_instance_id)
            _ensure_old_range_blocked(recovery, old_range_instance_id, _participant_user(participant))
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
