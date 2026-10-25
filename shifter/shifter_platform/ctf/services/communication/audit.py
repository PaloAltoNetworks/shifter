"""Strict, body-free authority evidence for scoped communication operations."""

from uuid import UUID

from ctf.services.audit import _entity_id_from_uuid
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log


def audit_communication_authority(
    *,
    event_id: UUID,
    actor_id: int,
    token_id: int | None,
    authority_source: str,
    request_id: str = "",
    operation: str = "admit",
) -> None:
    """Persist each target's live authority, including delegated and override use."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.COMMUNICATION,
            entity_id=_entity_id_from_uuid(event_id),
            entity_ref=str(event_id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.APIKEY if token_id is not None else AuditActorType.USER,
            actor_id=token_id if token_id is not None else actor_id,
            new_state={
                "event_id": str(event_id),
                "effective_actor_user_id": actor_id,
                "authority_source": authority_source,
                "operation": operation,
            },
            context="ctf_communication_authority",
            request_id=request_id,
        ),
        strict=True,
    )
