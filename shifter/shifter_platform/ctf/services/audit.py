"""CTF live-repair and range-recovery audit helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from risk_register.models import AuditLog
from risk_register.services import AuditEvent, audit_log

if TYPE_CHECKING:
    from ctf.models import CTFParticipant, CTFRangeRecovery


def _entity_id_from_uuid(entity_uuid: UUID) -> int:
    """Map a UUID to a positive int for AuditLog.entity_id."""
    return int.from_bytes(entity_uuid.bytes[:4], "big") % (2**31 - 1) or 1


def audit_live_flag_repair(
    *,
    actor_id: int,
    challenge_id: UUID,
    flag_id: UUID,
    event_id: UUID,
    action: str,
) -> None:
    """Record a live flag repair without storing flag plaintext or hashes."""
    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.CONFIG,
            entity_id=_entity_id_from_uuid(challenge_id),
            action=AuditLog.Action.UPDATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=actor_id,
            new_state={
                "ctf_live_flag_repair": action,
                "challenge_id": str(challenge_id),
                "flag_id": str(flag_id),
                "event_id": str(event_id),
            },
            context="ctf_live_flag_repair",
        )
    )


def audit_range_recovery(
    *,
    actor_id: int | None,
    recovery: CTFRangeRecovery,
    participant: CTFParticipant,
    previous_status: str,
) -> None:
    """Record a completed participant range-recovery operation (#1018).

    Takes the ``CTFRangeRecovery`` record and the participant rather than
    their individual fields (keeps the parameter count within the project's
    limit): ``entity_id``, the strategy, and the replacement reference are
    all read off ``recovery``, and the resulting status is read off
    ``participant`` (already updated by :func:`ctf.services.range.recovery._ensure_participant_repointed`
    by the time this runs). ``entity_id`` is the old (pre-recovery)
    ``RangeInstance.pk`` -- already a positive int, so no UUID-to-int mapping
    is needed here (unlike :func:`audit_live_flag_repair`). Participant/event
    identity and the replacement reference are carried as sanitized strings
    in ``new_state``. The old range is always destroyed (no
    disposition/forensics concept).
    """
    old_range_instance_id = recovery.old_range_instance_id
    new_state: dict[str, Any] = {
        "status": participant.range_status,
        "event_id": str(recovery.event_id),
        "participant_id": str(participant.pk),
        "strategy": recovery.strategy,
        "replacement_range_instance_id": recovery.replacement_range_instance_id,
        "replacement_request_id": (str(recovery.replacement_request_id) if recovery.replacement_request_id else None),
    }
    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=old_range_instance_id,
            action=AuditLog.Action.RECOVER,
            actor_type=AuditLog.ActorType.USER if actor_id else AuditLog.ActorType.SYSTEM,
            actor_id=actor_id,
            previous_state={"status": previous_status, "range_instance_id": old_range_instance_id},
            new_state=new_state,
            context="ctf_range_recovery",
        )
    )


def audit_spare_provisioning(
    *,
    actor_id: int | None,
    event_id: UUID,
    target_count: int,
    existing: int,
    created: int,
) -> None:
    """Record one event spare-pool top-up action (#1018).

    One row per ``provision_event_spares`` call, not one per range -- each
    individual CMS range creation is already audited by
    ``cms.services.create_range`` (``AuditLog.Action.PROVISION``).
    """
    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=_entity_id_from_uuid(event_id),
            action=AuditLog.Action.SPARE_PROVISION,
            actor_type=AuditLog.ActorType.USER if actor_id else AuditLog.ActorType.SYSTEM,
            actor_id=actor_id,
            new_state={
                "event_id": str(event_id),
                "target_count": target_count,
                "existing": existing,
                "created": created,
            },
            context="ctf_spare_provisioning",
        )
    )
